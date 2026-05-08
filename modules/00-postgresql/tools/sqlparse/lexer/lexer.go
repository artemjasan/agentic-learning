package lexer

import (
	"strings"
	"unicode"
)

// keywords maps SQL keyword strings (uppercased) to their token types.
// When the lexer reads a word like "select", it uppercases it and checks
// this map. If found, the word is a keyword; otherwise it's an identifier.
var keywords = map[string]TokenType{
	"SELECT": TokenSelect,
	"FROM":   TokenFrom,
	"WHERE":  TokenWhere,
	"AND":    TokenAnd,
	"OR":     TokenOr,
	"NOT":    TokenNot,
	"AS":     TokenAs,
	"ORDER":  TokenOrder,
	"BY":     TokenBy,
	"LIMIT":  TokenLimit,
	"INSERT": TokenInsert,
	"INTO":   TokenInto,
	"VALUES": TokenValues,
	"UPDATE": TokenUpdate,
	"SET":    TokenSet,
	"DELETE": TokenDelete,
}

// Lexer holds the state needed to scan through a SQL string one character
// at a time and produce tokens.
//
// The scanning works by maintaining a cursor (pos) and a "current character"
// (ch). We advance through the string character by character, deciding at
// each position what kind of token starts here.
type Lexer struct {
	input string // the full SQL string we're scanning
	pos   int    // current position in input (index of the next char to read)
	ch    byte   // the character at input[pos], or 0 if we've reached the end
}

// New creates a Lexer ready to scan the given SQL string.
// It loads the first character so we can start scanning immediately.
func New(input string) *Lexer {
	lex := &Lexer{input: input}
	lex.ch = lex.input[0]
	return lex
}

// Tokenize is a convenience function: it creates a lexer, reads ALL tokens
// from the input, and returns them as a slice. The last token is always EOF.
func Tokenize(input string) []Token {
	lex := New(input)
	var tokens []Token
	for {
		tok := lex.NextToken()
		tokens = append(tokens, tok)
		if tok.Type == TokenEOF {
			break
		}
	}
	return tokens
}

// NextToken reads the next token from the input.
//
// The algorithm:
//  1. Skip any whitespace (spaces, tabs, newlines)
//  2. If we've reached the end of input, return EOF
//  3. Look at the current character and decide what kind of token starts here:
//     - Punctuation (single char):  , . ; ( ) * + -
//     - Operators (1-2 chars):      = != <> < > <= >=
//     - String literal:             'hello world'
//     - Number:                     42 or 3.14
//     - Word:                       keyword (SELECT) or identifier (users)
func (lex *Lexer) NextToken() Token {
	lex.skipWhitespace()

	// End of input — no more tokens
	if lex.pos >= len(lex.input) {
		return Token{Type: TokenEOF, Pos: lex.pos}
	}

	// Save where this token starts (for error messages and source mapping)
	startPos := lex.pos
	char := lex.ch

	// --- Single-character tokens ---
	// These are unambiguous: one character = one token.
	switch char {
	case ',':
		lex.advance()
		return Token{Type: TokenComma, Value: ",", Pos: startPos}
	case '.':
		lex.advance()
		return Token{Type: TokenDot, Value: ".", Pos: startPos}
	case ';':
		lex.advance()
		return Token{Type: TokenSemicolon, Value: ";", Pos: startPos}
	case '(':
		lex.advance()
		return Token{Type: TokenLParen, Value: "(", Pos: startPos}
	case ')':
		lex.advance()
		return Token{Type: TokenRParen, Value: ")", Pos: startPos}
	case '*':
		lex.advance()
		return Token{Type: TokenStar, Value: "*", Pos: startPos}
	case '+':
		lex.advance()
		return Token{Type: TokenPlus, Value: "+", Pos: startPos}
	case '-':
		lex.advance()
		return Token{Type: TokenMinus, Value: "-", Pos: startPos}
	}

	// --- Multi-character operators ---
	// These might be 1 or 2 characters. We read the first char, then peek
	// at the next to decide. Example: '<' could be just '<' or '<=' or '<>'.
	switch char {
	case '=':
		lex.advance()
		return Token{Type: TokenEq, Value: "=", Pos: startPos}

	case '!':
		// '!' alone is invalid in SQL, but '!=' means "not equal"
		lex.advance()
		if lex.ch == '=' {
			lex.advance()
			return Token{Type: TokenNeq, Value: "!=", Pos: startPos}
		}
		return Token{Type: TokenEOF, Value: "!", Pos: startPos}

	case '<':
		// Could be: '<' (less than), '<=' (less or equal), '<>' (not equal)
		lex.advance()
		if lex.ch == '=' {
			lex.advance()
			return Token{Type: TokenLte, Value: "<=", Pos: startPos}
		}
		if lex.ch == '>' {
			lex.advance()
			return Token{Type: TokenNeq, Value: "<>", Pos: startPos}
		}
		return Token{Type: TokenLt, Value: "<", Pos: startPos}

	case '>':
		// Could be: '>' (greater than) or '>=' (greater or equal)
		lex.advance()
		if lex.ch == '=' {
			lex.advance()
			return Token{Type: TokenGte, Value: ">=", Pos: startPos}
		}
		return Token{Type: TokenGt, Value: ">", Pos: startPos}
	}

	// --- String literal ---
	// Strings in SQL are enclosed in single quotes: 'hello'
	// We read from the opening quote to the closing quote.
	if char == '\'' {
		return lex.readString()
	}

	// --- Number ---
	// Starts with a digit. We keep reading digits, and optionally a decimal
	// point followed by more digits (3.14).
	if isDigit(char) {
		return lex.readNumber()
	}

	// --- Word (keyword or identifier) ---
	// Starts with a letter or underscore. We read the full word, then check
	// if it's a SQL keyword. If not, it's an identifier (table/column name).
	if isLetter(char) {
		return lex.readWord()
	}

	// Unknown character — skip it and signal an error via EOF token
	lex.advance()
	return Token{Type: TokenEOF, Value: string(char), Pos: startPos}
}

// advance moves the cursor forward by one character.
// After advancing, lex.ch holds the new current character,
// or 0 if we've reached the end of the input.
func (lex *Lexer) advance() {
	lex.pos++
	if lex.pos >= len(lex.input) {
		lex.ch = 0
	} else {
		lex.ch = lex.input[lex.pos]
	}
}

// skipWhitespace advances past any spaces, tabs, and newlines.
// The lexer calls this at the start of NextToken so whitespace
// between tokens is invisible to the parser.
func (lex *Lexer) skipWhitespace() {
	for lex.pos < len(lex.input) && unicode.IsSpace(rune(lex.ch)) {
		lex.advance()
	}
}

// readWord reads a sequence of letters, digits, and underscores (a "word").
// Then checks if the word is a SQL keyword (case-insensitive).
// Returns a keyword token if found, otherwise an identifier token.
//
// Examples:
//
//	"SELECT" → Token{Type: TokenSelect, Value: "SELECT"}
//	"users"  → Token{Type: TokenIdent,  Value: "users"}
//	"User1"  → Token{Type: TokenIdent,  Value: "User1"}
func (lex *Lexer) readWord() Token {
	startPos := lex.pos

	// Consume all word characters: letters, digits, underscores
	for lex.pos < len(lex.input) && isWordChar(lex.ch) {
		lex.advance()
	}

	// Extract the word from the original input
	word := lex.input[startPos:lex.pos]

	// SQL keywords are case-insensitive: "select" == "SELECT" == "Select"
	if tokType, ok := keywords[strings.ToUpper(word)]; ok {
		return Token{Type: tokType, Value: word, Pos: startPos}
	}
	return Token{Type: TokenIdent, Value: word, Pos: startPos}
}

// readNumber reads an integer or decimal number.
// It consumes digits, and if it finds a dot followed by more digits,
// it reads the fractional part too.
//
// Examples:
//
//	"42"   → Token{Type: TokenNumber, Value: "42"}
//	"3.14" → Token{Type: TokenNumber, Value: "3.14"}
func (lex *Lexer) readNumber() Token {
	startPos := lex.pos

	// Read the integer part
	for lex.pos < len(lex.input) && isDigit(lex.ch) {
		lex.advance()
	}

	// If there's a decimal point, read the fractional part
	if lex.ch == '.' {
		lex.advance() // skip the dot
		for lex.pos < len(lex.input) && isDigit(lex.ch) {
			lex.advance()
		}
	}

	return Token{Type: TokenNumber, Value: lex.input[startPos:lex.pos], Pos: startPos}
}

// readString reads a single-quoted SQL string literal.
// It advances past the opening quote, reads until the closing quote,
// and includes both quotes in the token value.
//
// Example:
//
//	'hello' → Token{Type: TokenString, Value: "'hello'"}
func (lex *Lexer) readString() Token {
	startPos := lex.pos

	lex.advance() // skip the opening quote '

	// Read until we find the closing quote or reach end of input
	for lex.pos < len(lex.input) && lex.ch != '\'' {
		lex.advance()
	}

	// Skip the closing quote if present
	if lex.pos < len(lex.input) {
		lex.advance()
	}

	// Value includes the quotes: 'hello'
	return Token{Type: TokenString, Value: lex.input[startPos:lex.pos], Pos: startPos}
}

// isLetter returns true for characters that can start a word:
// uppercase/lowercase letters and underscore.
func isLetter(ch byte) bool {
	return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch == '_'
}

// isDigit returns true for decimal digit characters.
func isDigit(ch byte) bool {
	return ch >= '0' && ch <= '9'
}

// isWordChar returns true for characters that can appear inside a word
// (after the first character): letters, digits, underscore.
func isWordChar(ch byte) bool {
	return isLetter(ch) || isDigit(ch)
}
