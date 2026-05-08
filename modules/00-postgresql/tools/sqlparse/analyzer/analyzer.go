package analyzer

import (
	"fmt"
	"strings"

	"sqlparse/tree"
)

// Analyzer walks an AST and resolves names against the catalog cache.
//
// In real Postgres, this is the "parse analysis" phase (src/backend/parser/analyze.c).
// It transforms a raw parse tree (with string names) into a query tree (with
// resolved OIDs). The key function is transformStmt(), which dispatches to
// transformSelectStmt(), transformInsertStmt(), etc.
//
// Our analyzer validates names and reports errors, mirroring the checks
// the real analyzer performs before the query tree reaches the planner.
type Analyzer struct {
	catalog *CatalogCache
	errors  []string

	// scopeTables maps alias names (or table names) to their resolved
	// pg_class entries. This is our simplified version of Postgres's
	// range table (RTE list) — built from the FROM clause and used
	// to resolve column references.
	//
	// In real Postgres, each FROM item becomes a RangeTblEntry (RTE)
	// in the query's range table. The analyzer assigns each RTE an
	// index, and column references become Var nodes pointing to that index
	// (Var.varno = RTE index, Var.varattno = column number).
	scopeTables map[string]*PgClassEntry
}

// Analyze validates an AST against the catalog.
//
// This mirrors the entry point parse_analyze() in Postgres, which:
//  1. Creates a ParseState (our Analyzer)
//  2. Calls transformStmt() to walk the raw parse tree
//  3. Returns a Query node (analyzed tree) or raises an error
//
// We return a list of error strings instead of raising exceptions.
func Analyze(node tree.Node, catalog *CatalogCache) []string {
	analyzer := &Analyzer{
		catalog:     catalog,
		scopeTables: make(map[string]*PgClassEntry),
	}
	analyzer.transformStmt(node)
	return analyzer.errors
}

func (analyzer *Analyzer) addError(format string, args ...any) {
	analyzer.errors = append(analyzer.errors, fmt.Sprintf(format, args...))
}

// transformStmt dispatches to the appropriate handler based on statement type.
//
// In real Postgres: transformStmt() in analyze.c, a big switch on nodeTag.
func (analyzer *Analyzer) transformStmt(node tree.Node) {
	switch node.NodeType {
	case "SelectStmt":
		analyzer.transformSelectStmt(node)
	}
}

// transformSelectStmt analyzes a SELECT statement.
//
// In real Postgres (transformSelectStmt in analyze.c), the order is:
//  1. transformFromClause() — resolve tables, build range table
//  2. transformTargetList() — resolve SELECT columns
//  3. transformWhereClause() — resolve WHERE expression
//  4. transformSortClause() — resolve ORDER BY
//
// The FROM clause MUST be resolved first because SELECT and WHERE
// reference tables defined there.
func (analyzer *Analyzer) transformSelectStmt(node tree.Node) {
	// Step 1: resolve FROM clause — same order as real Postgres
	for _, child := range node.Children {
		if child.Field == "from_clause" {
			analyzer.transformFromClause(child)
		}
	}

	// Step 2+: resolve everything else
	for _, child := range node.Children {
		switch child.Field {
		case "target_list":
			analyzer.transformTargetList(child)
		case "where_clause":
			analyzer.transformExpr(child)
		case "sort_clause":
			for _, sortNode := range child.Children {
				for _, sortChild := range sortNode.Children {
					analyzer.transformExpr(sortChild)
				}
			}
		}
	}
}

// transformFromClause resolves table references and registers them
// in the scope.
//
// In real Postgres (transformFromClause in parse_clause.c):
//  1. For each FROM item, calls transformFromClauseItem()
//  2. Each resolved table becomes a RangeTblEntry (RTE)
//  3. RTEs are added to the query's range table (pstate->p_rtable)
//  4. The RTE index is used later by Var nodes to reference columns
func (analyzer *Analyzer) transformFromClause(node tree.Node) {
	for _, tableNode := range node.Children {
		if tableNode.NodeType == "RangeVar" {
			analyzer.transformRangeVar(tableNode)
		}
	}
}

// transformRangeVar resolves a single table reference.
//
// In real Postgres (transformRangeVar in parse_clause.c):
//  1. Calls RelnameGetRelid() to find the table's OID
//  2. Calls relation_open() to lock the relation
//  3. Creates a RangeTblEntry with the resolved OID
//  4. Registers aliases for qualified column references
func (analyzer *Analyzer) transformRangeVar(node tree.Node) {
	parts := strings.SplitN(node.Value, " AS ", 2)
	tableName := parts[0]
	alias := tableName
	if len(parts) == 2 {
		alias = parts[1]
	}

	// RelnameGetRelid: look up the table in the catalog
	entry := analyzer.catalog.RelnameGetRelid(tableName)
	if entry == nil {
		analyzer.addError("relation %q does not exist", tableName)
		return
	}

	analyzer.scopeTables[alias] = entry
}

// transformTargetList resolves column references in the SELECT list.
//
// In real Postgres (transformTargetList in parse_target.c):
// each target is processed by transformTargetEntry(), which calls
// transformExpr() on the expression and wraps it in a TargetEntry node.
func (analyzer *Analyzer) transformTargetList(node tree.Node) {
	for _, target := range node.Children {
		for _, child := range target.Children {
			analyzer.transformExpr(child)
		}
	}
}

// transformExpr walks an expression tree and resolves any column references.
//
// In real Postgres (transformExpr in parse_expr.c), this is a large
// recursive function that handles every expression type: ColumnRef, A_Expr,
// FuncCall, SubLink, CaseExpr, etc. Each node type has its own handler.
func (analyzer *Analyzer) transformExpr(node tree.Node) {
	switch node.NodeType {
	case "ColumnRef":
		analyzer.transformColumnRef(node)
	case "A_Expr":
		for _, child := range node.Children {
			analyzer.transformExpr(child)
		}
	case "BoolExpr":
		for _, child := range node.Children {
			analyzer.transformExpr(child)
		}
	}
	// A_Const (literals) need no resolution
}

// transformColumnRef resolves a column reference like "id" or "u.id".
//
// In real Postgres (transformColumnRef in parse_expr.c):
//  1. For qualified refs (u.id): look up alias "u" in the range table,
//     then find column "id" in that relation's pg_attribute entries.
//  2. For unqualified refs (id): scan ALL range table entries for a column
//     with that name. If found in multiple tables → ERROR: ambiguous.
//  3. On success: create a Var node with varno (RTE index) and varattno
//     (column number) — replacing the string name with numeric references.
func (analyzer *Analyzer) transformColumnRef(node tree.Node) {
	ref := node.Value

	if ref == "*" {
		return
	}

	parts := strings.SplitN(ref, ".", 2)

	if len(parts) == 2 {
		// Qualified: u.id → look up alias, then column
		alias := parts[0]
		colName := parts[1]

		table, exists := analyzer.scopeTables[alias]
		if !exists {
			analyzer.addError("missing FROM-clause entry for table %q", alias)
			return
		}

		col := analyzer.catalog.GetColumnByName(table, colName)
		if col == nil {
			analyzer.addError("column %q does not exist in table %q", colName, table.RelName)
		}
		return
	}

	// Unqualified: id → search all tables in scope
	colName := parts[0]
	var foundIn []string

	for alias, table := range analyzer.scopeTables {
		if analyzer.catalog.GetColumnByName(table, colName) != nil {
			foundIn = append(foundIn, alias)
		}
	}

	switch len(foundIn) {
	case 0:
		analyzer.addError("column %q does not exist", colName)
	case 1:
		// Resolved successfully
	default:
		analyzer.addError("column reference %q is ambiguous", colName)
	}
}
