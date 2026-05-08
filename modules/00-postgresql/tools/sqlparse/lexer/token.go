package lexer

import "fmt"

// TokenType tells us what kind of token this is.
type TokenType int

const (
	// Keywords
	TokenSelect TokenType = iota
	TokenFrom
	TokenWhere
	TokenAnd
	TokenOr
	TokenNot
	TokenAs
	TokenOrderBy // conceptually — we'll handle ORDER and BY as two keywords
	TokenOrder
	TokenBy
	TokenLimit
	TokenInsert
	TokenInto
	TokenValues
	TokenUpdate
	TokenSet
	TokenDelete

	// Literals & identifiers
	TokenIdent  // column name, table name
	TokenNumber // 42, 3.14
	TokenString // 'hello'

	// Operators
	TokenEq    // =
	TokenNeq   // != or <>
	TokenLt    // <
	TokenGt    // >
	TokenLte   // <=
	TokenGte   // >=
	TokenStar  // *
	TokenPlus  // +
	TokenMinus // -

	// Punctuation
	TokenComma     // ,
	TokenDot       // .
	TokenSemicolon // ;
	TokenLParen    // (
	TokenRParen    // )

	// Special
	TokenEOF // end of input
)

var tokenNames = map[TokenType]string{
	TokenSelect: "SELECT", TokenFrom: "FROM", TokenWhere: "WHERE",
	TokenAnd: "AND", TokenOr: "OR", TokenNot: "NOT", TokenAs: "AS",
	TokenOrder: "ORDER", TokenBy: "BY", TokenLimit: "LIMIT",
	TokenInsert: "INSERT", TokenInto: "INTO", TokenValues: "VALUES",
	TokenUpdate: "UPDATE", TokenSet: "SET", TokenDelete: "DELETE",
	TokenIdent: "IDENT", TokenNumber: "NUMBER", TokenString: "STRING",
	TokenEq: "=", TokenNeq: "!=", TokenLt: "<", TokenGt: ">",
	TokenLte: "<=", TokenGte: ">=", TokenStar: "*",
	TokenPlus: "+", TokenMinus: "-",
	TokenComma: ",", TokenDot: ".", TokenSemicolon: ";",
	TokenLParen: "(", TokenRParen: ")",
	TokenEOF: "EOF",
}

func (tt TokenType) String() string {
	if name, ok := tokenNames[tt]; ok {
		return name
	}
	return fmt.Sprintf("TOKEN(%d)", int(tt))
}

// Token is a single lexed unit.
type Token struct {
	Type    TokenType
	Value   string
	Pos     int // position in the original string
}

func (tok Token) String() string {
	return fmt.Sprintf("%-12s %q", tok.Type, tok.Value)
}
