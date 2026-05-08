package parser

import (
	"fmt"
	"slices"

	"sqlparse/lexer"
	"sqlparse/tree"
)

// Parser holds the token stream and a cursor position.
// It reads tokens left-to-right, building a tree as it goes.
type Parser struct {
	tokens []lexer.Token // all tokens from the lexer
	pos    int           // index of the current token
	sql    string        // original SQL string (for snippets in the tree)
}

// Parse tokenizes the SQL string with our lexer, then parses the tokens
// into a tree.Node that can be printed with tree.Print().
func Parse(sql string) (tree.Node, error) {
	tokens := lexer.Tokenize(sql)
	parser := &Parser{
		tokens: tokens,
		pos:    0,
		sql:    sql,
	}
	return parser.parseStatement()
}

// parseStatement looks at the first token to decide what kind of statement
// this is, then dispatches to the appropriate rule.
func (parser *Parser) parseStatement() (tree.Node, error) {
	switch parser.current().Type {
	case lexer.TokenSelect:
		return parser.parseSelect()
	default:
		tok := parser.current()
		return tree.Node{}, fmt.Errorf("unsupported statement: %s (%q) at position %d",
			tok.Type, tok.Value, tok.Pos)
	}
}

// --- Token navigation ---

// current returns the token at the current position.
func (parser *Parser) current() lexer.Token {
	if parser.pos >= len(parser.tokens) {
		return lexer.Token{Type: lexer.TokenEOF}
	}
	return parser.tokens[parser.pos]
}

// advance moves to the next token and returns the one we just consumed.
func (parser *Parser) advance() lexer.Token {
	tok := parser.current()
	parser.pos++
	return tok
}

// expect checks that the current token is the expected type, consumes it,
// and returns it. If the type doesn't match, it returns an error.
func (parser *Parser) expect(expected lexer.TokenType) (lexer.Token, error) {
	tok := parser.current()
	if tok.Type != expected {
		return tok, fmt.Errorf("expected %s, got %s (%q) at position %d",
			expected, tok.Type, tok.Value, tok.Pos)
	}
	parser.advance()
	return tok, nil
}

// currentIs checks whether the current token matches any of the given types.
func (parser *Parser) currentIs(types ...lexer.TokenType) bool {
	current := parser.current().Type
	return slices.Contains(types, current)
}

// --- Grammar rules ---
// Each function below corresponds to one rule in the grammar.
// They consume tokens and return tree.Node values.

// parseSelect handles:
//
//	SELECT targets FROM tables [WHERE condition] [ORDER BY ordering] [LIMIT number]
func (parser *Parser) parseSelect() (tree.Node, error) {
	node := tree.Node{NodeType: "SelectStmt"}

	// SELECT keyword
	if _, err := parser.expect(lexer.TokenSelect); err != nil {
		return node, err
	}

	// Target list (the columns): SELECT id, name, u.email
	targets, err := parser.parseTargets()
	if err != nil {
		return node, err
	}
	node.Children = append(node.Children, tree.Node{
		Field:    "target_list",
		Children: targets,
	})

	// FROM keyword + table list
	if _, err := parser.expect(lexer.TokenFrom); err != nil {
		return node, err
	}
	tables, err := parser.parseTables()
	if err != nil {
		return node, err
	}
	node.Children = append(node.Children, tree.Node{
		Field:    "from_clause",
		Children: tables,
	})

	// Optional: WHERE condition
	if parser.currentIs(lexer.TokenWhere) {
		parser.advance() // skip WHERE keyword
		condition, err := parser.parseCondition()
		if err != nil {
			return node, err
		}
		condition.Field = "where_clause"
		node.Children = append(node.Children, condition)
	}

	// Optional: ORDER BY
	if parser.currentIs(lexer.TokenOrder) {
		parser.advance() // skip ORDER
		if _, err := parser.expect(lexer.TokenBy); err != nil {
			return node, err
		}
		ordering, err := parser.parseOrdering()
		if err != nil {
			return node, err
		}
		node.Children = append(node.Children, tree.Node{
			Field:    "sort_clause",
			Children: ordering,
		})
	}

	// Optional: LIMIT
	if parser.currentIs(lexer.TokenLimit) {
		parser.advance() // skip LIMIT
		limitVal := parser.advance()
		node.Children = append(node.Children, tree.Node{
			Field:    "limit_count",
			NodeType: "A_Const",
			Value:    limitVal.Value,
		})
	}

	return node, nil
}

// parseTargets handles the column list after SELECT:
//
//	expression [AS alias] (, expression [AS alias])*
//
// Example: "id, u.name AS username, *"
func (parser *Parser) parseTargets() ([]tree.Node, error) {
	var targets []tree.Node

	for {
		target := tree.Node{NodeType: "ResTarget"}

		// Parse the expression (column reference, *, etc.)
		expr, err := parser.parseExpression()
		if err != nil {
			return nil, err
		}
		expr.Field = "val"
		target.Children = append(target.Children, expr)

		// Optional: AS alias
		if parser.currentIs(lexer.TokenAs) {
			parser.advance() // skip AS
			alias := parser.advance()
			target.Value = "AS " + alias.Value
		}

		targets = append(targets, target)

		// If next token is a comma, there are more targets
		if !parser.currentIs(lexer.TokenComma) {
			break
		}
		parser.advance() // skip the comma
	}

	return targets, nil
}

// parseTables handles the table list after FROM:
//
//	table_ref (, table_ref)*
//
// Example: "users AS u, orders AS o"
func (parser *Parser) parseTables() ([]tree.Node, error) {
	var tables []tree.Node

	for {
		table, err := parser.parseTableRef()
		if err != nil {
			return nil, err
		}
		tables = append(tables, table)

		if !parser.currentIs(lexer.TokenComma) {
			break
		}
		parser.advance() // skip the comma
	}

	return tables, nil
}

// parseTableRef handles a single table reference:
//
//	identifier [AS alias]
//
// Example: "users AS u" or just "users"
func (parser *Parser) parseTableRef() (tree.Node, error) {
	nameTok, err := parser.expect(lexer.TokenIdent)
	if err != nil {
		return tree.Node{}, err
	}

	name := nameTok.Value

	// Optional: AS alias
	if parser.currentIs(lexer.TokenAs) {
		parser.advance() // skip AS
		aliasTok := parser.advance()
		name += " AS " + aliasTok.Value
	} else if parser.currentIs(lexer.TokenIdent) {
		// Implicit alias (no AS keyword): "users u"
		aliasTok := parser.advance()
		name += " AS " + aliasTok.Value
	}

	return tree.Node{
		NodeType: "RangeVar",
		Value:    name,
		Snippet:  tree.Snippet(parser.sql, nameTok.Pos),
	}, nil
}

// parseCondition handles WHERE conditions with AND/OR:
//
//	comparison [(AND | OR) comparison]*
//
// Example: "id = 5 AND name != 'admin'"
//
// When AND/OR connects multiple comparisons, we wrap them in a BoolExpr
// node, matching how Postgres represents them.
func (parser *Parser) parseCondition() (tree.Node, error) {
	// Parse the first comparison
	left, err := parser.parseComparison()
	if err != nil {
		return tree.Node{}, err
	}

	// Check for AND/OR chains
	if parser.currentIs(lexer.TokenAnd, lexer.TokenOr) {
		opTok := parser.advance()
		opName := "AND"
		if opTok.Type == lexer.TokenOr {
			opName = "OR"
		}

		right, err := parser.parseCondition() // recursive — handles chains
		if err != nil {
			return tree.Node{}, err
		}

		return tree.Node{
			NodeType: "BoolExpr",
			Value:    opName,
			Snippet:  tree.Snippet(parser.sql, opTok.Pos),
			Children: []tree.Node{left, right},
		}, nil
	}

	return left, nil
}

// parseComparison handles a single comparison:
//
//	expression operator expression
//
// Example: "id = 5" or "o.total >= 99.5"
func (parser *Parser) parseComparison() (tree.Node, error) {
	left, err := parser.parseExpression()
	if err != nil {
		return tree.Node{}, err
	}

	// Check for comparison operator
	if parser.currentIs(lexer.TokenEq, lexer.TokenNeq, lexer.TokenLt,
		lexer.TokenGt, lexer.TokenLte, lexer.TokenGte) {

		opTok := parser.advance()

		right, err := parser.parseExpression()
		if err != nil {
			return tree.Node{}, err
		}

		left.Field = "left"
		right.Field = "right"

		return tree.Node{
			NodeType: "A_Expr",
			Value:    opTok.Value,
			Snippet:  tree.Snippet(parser.sql, opTok.Pos),
			Children: []tree.Node{left, right},
		}, nil
	}

	// No operator — just the expression itself (e.g., a boolean column)
	return left, nil
}

// parseExpression handles a single value or column reference:
//   - Column reference: "id" or "u.id"
//   - Star: "*"
//   - Number: 42 or 3.14
//   - String: 'hello'
//   - Parenthesized condition: (id = 5 AND name = 'admin')
func (parser *Parser) parseExpression() (tree.Node, error) {
	tok := parser.current()

	switch tok.Type {
	case lexer.TokenIdent:
		// Could be "id" or "u.id" (qualified with table alias)
		parser.advance()
		name := tok.Value

		// Check for dot: u.id
		if parser.currentIs(lexer.TokenDot) {
			parser.advance() // skip dot
			colTok := parser.advance()
			name += "." + colTok.Value
		}

		return tree.Node{
			NodeType: "ColumnRef",
			Value:    name,
			Snippet:  tree.Snippet(parser.sql, tok.Pos),
		}, nil

	case lexer.TokenStar:
		parser.advance()
		return tree.Node{
			NodeType: "ColumnRef",
			Value:    "*",
			Snippet:  tree.Snippet(parser.sql, tok.Pos),
		}, nil

	case lexer.TokenNumber:
		parser.advance()
		return tree.Node{
			NodeType: "A_Const",
			Value:    tok.Value,
		}, nil

	case lexer.TokenString:
		parser.advance()
		return tree.Node{
			NodeType: "A_Const",
			Value:    tok.Value,
		}, nil

	case lexer.TokenLParen:
		// Parenthesized expression: (condition)
		parser.advance() // skip (
		inner, err := parser.parseCondition()
		if err != nil {
			return tree.Node{}, err
		}
		if _, err := parser.expect(lexer.TokenRParen); err != nil {
			return tree.Node{}, err
		}
		return inner, nil

	default:
		return tree.Node{}, fmt.Errorf("unexpected token %s (%q) at position %d",
			tok.Type, tok.Value, tok.Pos)
	}
}

// parseOrdering handles the expressions after ORDER BY:
//
//	expression [ASC | DESC] (, expression [ASC | DESC])*
func (parser *Parser) parseOrdering() ([]tree.Node, error) {
	var items []tree.Node

	for {
		expr, err := parser.parseExpression()
		if err != nil {
			return nil, err
		}
		expr.Field = "node"

		dir := ""
		// Check for ASC/DESC — these are identifiers to our lexer since
		// we didn't add them as keywords (they're context-dependent)
		if parser.currentIs(lexer.TokenIdent) {
			word := parser.current().Value
			if word == "ASC" || word == "asc" {
				dir = "ASC"
				parser.advance()
			} else if word == "DESC" || word == "desc" {
				dir = "DESC"
				parser.advance()
			}
		}

		items = append(items, tree.Node{
			NodeType: "SortBy",
			Value:    dir,
			Children: []tree.Node{expr},
		})

		if !parser.currentIs(lexer.TokenComma) {
			break
		}
		parser.advance()
	}

	return items, nil
}
