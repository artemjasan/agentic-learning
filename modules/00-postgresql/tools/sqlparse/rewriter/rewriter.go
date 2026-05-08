package rewriter

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"

	"sqlparse/parser"
	"sqlparse/tree"
)

// Rewriter expands view references in a query tree.
//
// In real Postgres, the rewriter (src/backend/rewrite/rewriteHandler.c)
// applies rewrite rules stored in pg_rewrite. Views are implemented as
// SELECT rules: when you query a view, the rewriter replaces the view's
// range table entry with the view's underlying query.
//
// The key function is QueryRewrite(), which:
//  1. Walks the query's range table looking for view references
//  2. For each view: looks up its rewrite rule in pg_rewrite
//  3. The rule contains a pre-parsed query tree (stored as a nodeToString)
//  4. Substitutes the view reference with the rule's query tree
//  5. Adjusts variable references (Var.varno) to point to the new RTEs
//
// Our implementation loads view definitions from pg_views and re-parses
// them with our parser — simulating the same substitution.
type Rewriter struct {
	db    *sql.DB
	views map[string]string // view name → SQL definition (cached lazily)
}

// NewRewriter creates a rewriter connected to the database.
//
// In real Postgres, the rewriter doesn't maintain its own cache — it uses
// the SysCache to look up pg_rewrite entries, which are cached the same
// way as pg_class entries (lazy, per-backend).
func NewRewriter(dsn string) (*Rewriter, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}

	return &Rewriter{
		db:    db,
		views: make(map[string]string),
	}, nil
}

// Close releases the database connection.
func (rw *Rewriter) Close() {
	rw.db.Close()
}

// Rewrite walks the query tree and expands any view references.
//
// In real Postgres (QueryRewrite in rewriteHandler.c):
//  1. For each RTE in the range table with relkind='v' (view):
//  2. Look up the _RETURN rule in pg_rewrite for that view's OID
//  3. Copy the rule's action query tree
//  4. Replace the view RTE with the subquery
//  5. Adjust all Var references that pointed to the view's RTE
//
// Returns the original tree if no views are found, or a rewritten tree
// with views expanded.
func (rw *Rewriter) Rewrite(node tree.Node) tree.Node {
	if node.NodeType != "SelectStmt" {
		return node
	}

	rewritten := node
	rewritten.Children = make([]tree.Node, len(node.Children))
	copy(rewritten.Children, node.Children)

	for i, child := range rewritten.Children {
		if child.Field == "from_clause" {
			rewritten.Children[i] = rw.rewriteFromClause(child)
		}
	}

	return rewritten
}

// rewriteFromClause checks each table reference in FROM — if it's a view,
// expand it.
func (rw *Rewriter) rewriteFromClause(from tree.Node) tree.Node {
	result := from
	result.Children = make([]tree.Node, len(from.Children))

	for i, tableRef := range from.Children {
		if tableRef.NodeType == "RangeVar" {
			expanded := rw.expandIfView(tableRef)
			result.Children[i] = expanded
		} else {
			result.Children[i] = tableRef
		}
	}

	return result
}

// expandIfView checks if a RangeVar refers to a view. If so, it replaces
// the RangeVar with a Subquery node containing the view's parsed definition.
//
// In real Postgres, this is where the _RETURN rule from pg_rewrite gets
// applied. The rule's action (a pre-stored query tree) replaces the view's
// RTE. The stored tree was parsed and analyzed at CREATE VIEW time, so
// no re-parsing is needed — it's just a tree copy.
//
// We re-parse the view's SQL definition since we don't store pre-parsed trees.
func (rw *Rewriter) expandIfView(tableRef tree.Node) tree.Node {
	// Extract the table name (strip alias if present)
	tableName := tableRef.Value
	for _, sep := range []string{" AS ", " as "} {
		if idx := indexOf(tableName, sep); idx >= 0 {
			tableName = tableName[:idx]
			break
		}
	}

	// Look up view definition — like checking pg_rewrite for a _RETURN rule
	viewDef := rw.lookupView(tableName)
	if viewDef == "" {
		return tableRef // not a view, keep as-is
	}

	fmt.Printf("  %s[rewrite]%s  expanding view %s%s%s → %s%s%s\n",
		"\033[33m", "\033[0m",
		"\033[36m", tableName, "\033[0m",
		"\033[2m", viewDef, "\033[0m")

	// Parse the view's definition with our parser
	viewTree, err := parser.Parse(viewDef)
	if err != nil {
		fmt.Printf("  %s[rewrite error]%s  failed to parse view: %v\n",
			"\033[31m", "\033[0m", err)
		return tableRef
	}

	// Replace the RangeVar with a Subquery node
	return tree.Node{
		NodeType: "Subquery",
		Value:    tableName,
		Children: []tree.Node{viewTree},
	}
}

// lookupView checks if a table name is actually a view and returns its
// SQL definition. Uses lazy caching like the catalog cache.
//
// In real Postgres, this is a SysCache lookup on pg_rewrite, searching
// for a rule with ev_class = view's OID and rulename = '_RETURN'.
func (rw *Rewriter) lookupView(name string) string {
	// Cache hit
	if def, exists := rw.views[name]; exists {
		return def
	}

	// Cache miss — query pg_views (which reads pg_rewrite internally)
	var definition string
	err := rw.db.QueryRow(`
		SELECT definition FROM pg_views
		WHERE viewname = $1 AND schemaname = 'public'
	`, name).Scan(&definition)
	if err != nil {
		rw.views[name] = "" // negative cache — remember it's not a view
		return ""
	}

	rw.views[name] = definition
	return definition
}

func indexOf(s, substr string) int {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}
