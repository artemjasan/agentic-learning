# Chapter 4b: SQL Parsing Internals

## Plan

### 1. See the real parse tree
Enable `debug_print_parse` and `debug_print_rewritten` in the Postgres config. Run a simple query, read the raw parse tree from server logs. Understand the node types Postgres uses internally (SelectStmt, RangeVar, ColumnRef, etc.).

*Hands-on:* Set the GUCs, run `SELECT id, name FROM users WHERE id = 5`, read the parse tree output. Then read the rewritten tree to see the difference.

### 2. Parse SQL with pg_query_go
Use the `pg_query_go` library — a Go wrapper around Postgres's actual parser extracted as a standalone C library. Parse real SQL strings, get the parse tree as Go structs, walk it programmatically.

*Hands-on:* Write a Go tool that takes a SQL string, parses it, and pretty-prints the AST. Try various queries (SELECT, INSERT, JOIN, subquery) and observe how the tree structure changes.

### 3. Build a lexer from scratch
Write a basic SQL lexer in Go that tokenizes a SQL string into tokens: keywords (SELECT, FROM, WHERE), identifiers, numbers, strings, operators, punctuation. Understand how the lexer handles whitespace, quoted identifiers, string literals.

*Hands-on:* Build the lexer, test with `SELECT id, name FROM users WHERE id = 5`. Output a stream of typed tokens.

### 4. Build a parser from scratch
Write a recursive descent parser in Go for a tiny SQL subset:
- `SELECT column [, column...] FROM table [WHERE column = value]`

Parse into an AST (Go structs). Understand the grammar rules, operator precedence (for WHERE expressions), and error reporting.

*Hands-on:* Parse a simple SELECT, print the AST. Then extend to support `*`, `AND`/`OR` in WHERE, `ORDER BY`, `LIMIT`. Compare your AST to what pg_query_go produces.

### 5. Build a basic analyzer
Write a name resolver in Go. Given a simple schema definition (table names, column names, types), walk the parse tree and:
- Resolve table names → check they exist
- Resolve column names → check they belong to the referenced table
- Check basic type compatibility (comparing int to string → error)

*Hands-on:* Define a schema for `users(id int, name text, email text)`. Analyze valid and invalid queries. Produce clear error messages like Postgres does ("column X does not exist", "table Y does not exist").

### 6. Build a basic rewriter
Implement view expansion. Given a map of view definitions (view name → underlying query), walk the parse tree and replace view references with their definitions.

*Hands-on:* Define `user_emails` as `SELECT id, email FROM users`. Parse `SELECT * FROM user_emails WHERE id = 5`, rewrite it, output the transformed query. Verify it matches what Postgres does.

### What you'll know after this chapter
- How SQL text becomes a structured tree (parse tree → query tree)
- The actual node types Postgres uses internally
- How lexing and parsing work mechanically (tokens → grammar → AST)
- How name resolution works (catalog lookups → resolved references)
- How view expansion works (rewrite rules → transformed query tree)
- Confidence to read Postgres parser source code

### Out of scope
- Planner/optimizer internals → Chapter 5
- Full SQL grammar (JOINs, subqueries, CTEs, window functions) — only a subset
- Type coercion and implicit casts
- Rule system beyond simple views

---

## Findings

### Real Parse Tree (debug_print_parse)
Enabled `debug_print_parse` on the server, observed the internal representation Postgres produces for `SELECT id, name FROM users WHERE id = 5`. Key discovery: the output showed the **analyzed** query tree (QUERY node with VAR nodes containing resolved OIDs), not the raw parse tree. String names were already replaced with numeric references: `users` → relid 16507, `id` → varattno 1, `=` → opno 96, `int4` → vartype 23.

### pg_query_go
Used the `pg_query_go` library (Postgres's actual C parser compiled as a standalone library) to parse SQL in Go. This produces the **raw** parse tree — before analysis. Key difference from the server log output: names are still strings (ColumnRef "id", RangeVar "users", A_Expr "="), not OIDs. Built a tree printer that shows AST node types with source snippets.

### Lexer (built from scratch)
Wrote a SQL lexer in Go that tokenizes SQL into keywords, identifiers, numbers, strings, operators, and punctuation. Core algorithm: walk the string character by character, decide what kind of token starts at each position. Keywords are identified by checking a lookup map after reading a word. SQL keywords are case-insensitive.

### Parser (built from scratch)
Wrote a recursive descent parser for a SELECT subset. Each grammar rule becomes a Go function: `parseSelect`, `parseTargets`, `parseTables`, `parseCondition`, `parseExpression`. The parser produces `tree.Node` values — the same type used by pg_query_go, so both parsers share the same tree printer. Compared output side-by-side with the real Postgres parser — nearly identical trees.

### Analyzer (built from scratch)
Wrote an analyzer that resolves names against the real database catalog. Architecture mirrors Postgres internals:
- **CatalogCache** — per-backend lazy cache, loads table definitions from pg_class/pg_attribute on first access (MISS), returns cached entries on subsequent lookups (HIT). Mirrors Postgres's SysCache.
- **RelnameGetRelid()** — resolves table names to OIDs
- **transformSelectStmt()** — mirrors analyze.c: resolves FROM first (builds scope), then resolves SELECT columns and WHERE conditions
- **transformColumnRef()** — handles qualified (u.id) and unqualified (id) references, detects ambiguous columns

Key insight: the catalog cache exists because accessing shared_buffers requires LWLocks. Private cache = no locks, nanosecond lookups. The cache loads the full table definition (all columns), not just referenced ones.

### Rewriter (built from scratch)
Wrote a rewriter that expands view references. Looks up view definitions from pg_views (which reads pg_rewrite internally), parses the view's SQL, and substitutes the RangeVar with a Subquery containing the view's parsed tree. In real Postgres, views are stored as pre-parsed query trees in pg_rewrite — no re-parsing needed. The rule system also handles custom rules and INSTEAD OF rules, but views are the main use case.

### Tool: sqlparse
Built a Go CLI tool with five commands:
- `sqlparse parse "SQL"` — parse with the real Postgres parser (pg_query_go)
- `sqlparse lex "SQL"` — tokenize with our lexer
- `sqlparse myparse "SQL"` — parse with our lexer + parser
- `sqlparse analyze "SQL" ["SQL"...]` — parse + analyze against real DB catalog (shows cache hits/misses)
- `sqlparse rewrite "SQL"` — parse + expand views (shows before/after trees)

All commands share the same `tree.Node` type and tree printer.

---

## Retro

### Summary
Built the full pre-planner SQL pipeline from scratch in Go: lexer → parser → analyzer → rewriter. Each component mirrors real Postgres architecture with documented function names and data structures. The catalog cache demonstrates why per-backend private caching exists (avoid shared memory lock contention). The tool produces AST trees comparable to Postgres's real parser output.

### Key Takeaways
- The parser produces string names, the analyzer turns them into resolved references (OIDs) — these are two distinct stages
- Catalog cache is per-backend, lazy, and caches full table definitions — exists to avoid LWLock contention on shared_buffers
- Views are syntactic sugar implemented as rewrite rules — the rewriter eliminates them before the planner sees the query
- Recursive descent parsing maps grammar rules directly to functions — each rule = one function
- A lexer is just a character-by-character state machine that classifies characters into token types

### Connections
- **Ch 1 (Physical Storage)**: catalog tables (pg_class, pg_attribute) are regular heap tables with regular pages
- **Ch 2 (Shared Buffers)**: catalog cache avoids repeated shared_buffers access — LWLock contention is the motivation
- **Ch 4 (Architecture)**: catalog cache is part of backend private memory (VmData ~3MB)
- **Ch 5 (Query Execution)**: the planner receives the analyzed, rewritten query tree — our pipeline feeds directly into it
- **Ch 21 (Triggers & Rules)**: the rule system powers views and could power custom query rewriting
