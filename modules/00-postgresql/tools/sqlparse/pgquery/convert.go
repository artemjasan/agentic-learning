package pgquery

import (
	"fmt"
	"strings"

	pg_query "github.com/pganalyze/pg_query_go/v6"
	"sqlparse/tree"
	"google.golang.org/protobuf/proto"
)

func Convert(sql string, result *pg_query.ParseResult) []tree.Node {
	var nodes []tree.Node
	for _, stmt := range result.GetStmts() {
		nodes = append(nodes, convertNode(sql, stmt.GetStmt(), "")...)
	}
	return nodes
}

func convertNode(sql string, node *pg_query.Node, field string) []tree.Node {
	if node == nil {
		return nil
	}
	msg := nodeMessage(node)
	if msg == nil {
		return nil
	}
	n := convert(sql, msg, field)
	return []tree.Node{n}
}

func convertWithField(sql string, node *pg_query.Node, field string) tree.Node {
	if node == nil {
		return tree.Node{Field: field, Value: "∅"}
	}
	msg := nodeMessage(node)
	if msg == nil {
		return tree.Node{Field: field, Value: "?"}
	}
	n := convert(sql, msg, "")
	n.Field = field
	return n
}

func convert(sql string, msg proto.Message, field string) tree.Node {
	switch m := msg.(type) {
	case *pg_query.SelectStmt:
		return convertSelectStmt(sql, m, field)
	case *pg_query.A_Expr:
		return convertAExpr(sql, m, field)
	case *pg_query.ColumnRef:
		return convertColumnRef(sql, m, field)
	case *pg_query.RangeVar:
		return convertRangeVar(sql, m, field)
	case *pg_query.ResTarget:
		return convertResTarget(sql, m, field)
	case *pg_query.JoinExpr:
		return convertJoinExpr(sql, m, field)
	case *pg_query.SortBy:
		return convertSortBy(sql, m, field)
	case *pg_query.A_Const:
		return convertAConst(m, field)
	case *pg_query.FuncCall:
		return convertFuncCall(sql, m, field)
	case *pg_query.BoolExpr:
		return convertBoolExpr(sql, m, field)
	case *pg_query.TypeCast:
		return convertTypeCast(sql, m, field)
	case *pg_query.NullTest:
		return convertNullTest(sql, m, field)
	case *pg_query.SubLink:
		return tree.Node{Field: field, NodeType: "SubLink", Snippet: tree.Snippet(sql, int(m.GetLocation()))}
	default:
		name := string(msg.ProtoReflect().Descriptor().Name())
		return tree.Node{Field: field, NodeType: name}
	}
}

func convertSelectStmt(sql string, s *pg_query.SelectStmt, field string) tree.Node {
	item := tree.Node{Field: field, NodeType: "SelectStmt"}

	if len(s.GetTargetList()) > 0 {
		targets := tree.Node{Field: "target_list"}
		for _, t := range s.GetTargetList() {
			if msg := nodeMessage(t); msg != nil {
				targets.Children = append(targets.Children, convert(sql, msg, ""))
			}
		}
		item.Children = append(item.Children, targets)
	}

	if len(s.GetFromClause()) > 0 {
		from := tree.Node{Field: "from_clause"}
		for _, f := range s.GetFromClause() {
			if msg := nodeMessage(f); msg != nil {
				from.Children = append(from.Children, convert(sql, msg, ""))
			}
		}
		item.Children = append(item.Children, from)
	}

	if s.GetWhereClause() != nil {
		item.Children = append(item.Children, convertWithField(sql, s.GetWhereClause(), "where_clause"))
	}

	if len(s.GetGroupClause()) > 0 {
		group := tree.Node{Field: "group_clause"}
		for _, g := range s.GetGroupClause() {
			if msg := nodeMessage(g); msg != nil {
				group.Children = append(group.Children, convert(sql, msg, ""))
			}
		}
		item.Children = append(item.Children, group)
	}

	if s.GetHavingClause() != nil {
		item.Children = append(item.Children, convertWithField(sql, s.GetHavingClause(), "having_clause"))
	}

	if len(s.GetSortClause()) > 0 {
		sort := tree.Node{Field: "sort_clause"}
		for _, o := range s.GetSortClause() {
			if msg := nodeMessage(o); msg != nil {
				sort.Children = append(sort.Children, convert(sql, msg, ""))
			}
		}
		item.Children = append(item.Children, sort)
	}

	if s.GetLimitCount() != nil {
		item.Children = append(item.Children, convertWithField(sql, s.GetLimitCount(), "limit_count"))
	}

	if s.GetLimitOffset() != nil {
		item.Children = append(item.Children, convertWithField(sql, s.GetLimitOffset(), "limit_offset"))
	}

	return item
}

func convertResTarget(sql string, r *pg_query.ResTarget, field string) tree.Node {
	item := tree.Node{Field: field, NodeType: "ResTarget"}
	if r.GetName() != "" {
		item.Value = fmt.Sprintf("AS %s", r.GetName())
	}
	if r.GetVal() != nil {
		item.Children = append(item.Children, convertWithField(sql, r.GetVal(), "val"))
	}
	return item
}

func convertColumnRef(sql string, c *pg_query.ColumnRef, field string) tree.Node {
	var parts []string
	for _, f := range c.GetFields() {
		if m := nodeMessage(f); m != nil {
			if s, ok := m.(*pg_query.String); ok {
				parts = append(parts, s.GetSval())
			} else if _, ok := m.(*pg_query.A_Star); ok {
				parts = append(parts, "*")
			}
		}
	}
	return tree.Node{
		Field:    field,
		NodeType: "ColumnRef",
		Value:    strings.Join(parts, "."),
		Snippet:  tree.Snippet(sql, int(c.GetLocation())),
	}
}

func convertRangeVar(sql string, r *pg_query.RangeVar, field string) tree.Node {
	name := r.GetRelname()
	if r.GetSchemaname() != "" {
		name = r.GetSchemaname() + "." + name
	}
	if r.GetAlias() != nil {
		name += " AS " + r.GetAlias().GetAliasname()
	}
	return tree.Node{
		Field:    field,
		NodeType: "RangeVar",
		Value:    name,
		Snippet:  tree.Snippet(sql, int(r.GetLocation())),
	}
}

func convertAExpr(sql string, a *pg_query.A_Expr, field string) tree.Node {
	op := "?"
	for _, n := range a.GetName() {
		if s := n.GetString_(); s != nil {
			op = s.GetSval()
		}
	}

	item := tree.Node{
		Field:    field,
		NodeType: "A_Expr",
		Value:    op,
		Snippet:  tree.Snippet(sql, int(a.GetLocation())),
	}

	if a.GetLexpr() != nil {
		item.Children = append(item.Children, convertWithField(sql, a.GetLexpr(), "left"))
	}
	if a.GetRexpr() != nil {
		item.Children = append(item.Children, convertWithField(sql, a.GetRexpr(), "right"))
	}
	return item
}

func convertAConst(c *pg_query.A_Const, field string) tree.Node {
	val := "?"
	switch v := c.GetVal().(type) {
	case *pg_query.A_Const_Ival:
		val = fmt.Sprintf("%d", v.Ival.GetIval())
	case *pg_query.A_Const_Sval:
		val = fmt.Sprintf("'%s'", v.Sval.GetSval())
	case *pg_query.A_Const_Fval:
		val = v.Fval.GetFval()
	case *pg_query.A_Const_Boolval:
		val = fmt.Sprintf("%v", v.Boolval.GetBoolval())
	}
	return tree.Node{Field: field, NodeType: "A_Const", Value: val}
}

func convertJoinExpr(sql string, j *pg_query.JoinExpr, field string) tree.Node {
	joinTypes := map[pg_query.JoinType]string{
		pg_query.JoinType_JOIN_INNER: "INNER",
		pg_query.JoinType_JOIN_LEFT:  "LEFT",
		pg_query.JoinType_JOIN_FULL:  "FULL",
		pg_query.JoinType_JOIN_RIGHT: "RIGHT",
	}
	jt := joinTypes[j.GetJointype()]
	if jt == "" {
		jt = "INNER"
	}

	item := tree.Node{Field: field, NodeType: "JoinExpr", Value: jt}

	if j.GetLarg() != nil {
		item.Children = append(item.Children, convertWithField(sql, j.GetLarg(), "left"))
	}
	if j.GetRarg() != nil {
		item.Children = append(item.Children, convertWithField(sql, j.GetRarg(), "right"))
	}
	if j.GetQuals() != nil {
		item.Children = append(item.Children, convertWithField(sql, j.GetQuals(), "quals"))
	}
	return item
}

func convertSortBy(sql string, s *pg_query.SortBy, field string) tree.Node {
	dir := ""
	switch s.GetSortbyDir() {
	case pg_query.SortByDir_SORTBY_ASC:
		dir = "ASC"
	case pg_query.SortByDir_SORTBY_DESC:
		dir = "DESC"
	}

	item := tree.Node{Field: field, NodeType: "SortBy", Value: dir}
	if s.GetNode() != nil {
		item.Children = append(item.Children, convertWithField(sql, s.GetNode(), "node"))
	}
	return item
}

func convertFuncCall(sql string, f *pg_query.FuncCall, field string) tree.Node {
	var parts []string
	for _, n := range f.GetFuncname() {
		if s := n.GetString_(); s != nil {
			parts = append(parts, s.GetSval())
		}
	}

	name := strings.Join(parts, ".") + "()"
	if f.GetAggStar() {
		name = strings.Join(parts, ".") + "(*)"
	}

	item := tree.Node{
		Field:    field,
		NodeType: "FuncCall",
		Value:    name,
		Snippet:  tree.Snippet(sql, int(f.GetLocation())),
	}

	for i, arg := range f.GetArgs() {
		item.Children = append(item.Children, convertWithField(sql, arg, fmt.Sprintf("arg%d", i)))
	}
	return item
}

func convertBoolExpr(sql string, b *pg_query.BoolExpr, field string) tree.Node {
	ops := map[pg_query.BoolExprType]string{
		pg_query.BoolExprType_AND_EXPR: "AND",
		pg_query.BoolExprType_OR_EXPR:  "OR",
		pg_query.BoolExprType_NOT_EXPR: "NOT",
	}

	item := tree.Node{
		Field:    field,
		NodeType: "BoolExpr",
		Value:    ops[b.GetBoolop()],
		Snippet:  tree.Snippet(sql, int(b.GetLocation())),
	}

	for _, arg := range b.GetArgs() {
		if msg := nodeMessage(arg); msg != nil {
			item.Children = append(item.Children, convert(sql, msg, ""))
		}
	}
	return item
}

func convertTypeCast(sql string, t *pg_query.TypeCast, field string) tree.Node {
	item := tree.Node{Field: field, NodeType: "TypeCast"}
	if t.GetArg() != nil {
		item.Children = append(item.Children, convertWithField(sql, t.GetArg(), "arg"))
	}
	if t.GetTypeName() != nil {
		var names []string
		for _, n := range t.GetTypeName().GetNames() {
			if s := n.GetString_(); s != nil {
				names = append(names, s.GetSval())
			}
		}
		item.Value = strings.Join(names, ".")
	}
	return item
}

func convertNullTest(sql string, n *pg_query.NullTest, field string) tree.Node {
	val := "IS NULL"
	if n.GetNulltesttype() == pg_query.NullTestType_IS_NOT_NULL {
		val = "IS NOT NULL"
	}
	item := tree.Node{Field: field, NodeType: "NullTest", Value: val}
	if n.GetArg() != nil {
		item.Children = append(item.Children, convertWithField(sql, n.GetArg(), "arg"))
	}
	return item
}

func nodeMessage(node *pg_query.Node) proto.Message {
	if node == nil {
		return nil
	}
	ref := node.ProtoReflect()
	oneofDesc := ref.Descriptor().Oneofs().Get(0)
	field := ref.WhichOneof(oneofDesc)
	if field == nil {
		return nil
	}
	return ref.Get(field).Message().Interface().(proto.Message)
}
