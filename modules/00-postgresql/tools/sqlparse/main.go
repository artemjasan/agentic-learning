package main

import (
	"fmt"
	"os"

	pg_query "github.com/pganalyze/pg_query_go/v6"
	"sqlparse/analyzer"
	"sqlparse/lexer"
	"sqlparse/parser"
	"sqlparse/pgquery"
	"sqlparse/rewriter"
	"sqlparse/tree"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: sqlparse <command> \"SQL\"\n")
		fmt.Fprintf(os.Stderr, "  sqlparse parse  \"SELECT ...\"  — parse with pg_query (real Postgres parser)\n")
		fmt.Fprintf(os.Stderr, "  sqlparse lex    \"SELECT ...\"  — tokenize with our lexer\n")
		fmt.Fprintf(os.Stderr, "  sqlparse myparse \"SELECT ...\" — parse with our lexer + parser\n")
		fmt.Fprintf(os.Stderr, "  sqlparse analyze \"SELECT ...\" — parse + analyze (check names against schema)\n")
		fmt.Fprintf(os.Stderr, "  sqlparse rewrite \"SELECT ...\" — parse + rewrite (expand views)\n")
		os.Exit(1)
	}

	cmd := os.Args[1]
	sql := os.Args[2]

	switch cmd {
	case "parse":
		doParse(sql)
	case "lex":
		doLex(sql)
	case "myparse":
		doMyParse(sql)
	case "analyze":
		doAnalyze(os.Args[2:]...)
	case "rewrite":
		doRewrite(sql)
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		os.Exit(1)
	}
}

func doParse(sql string) {
	result, err := pg_query.Parse(sql)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Parse error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("\n%s%s%s\n\n", tree.Dim, sql, tree.Reset)

	nodes := pgquery.Convert(sql, result)
	for _, n := range nodes {
		tree.Print(n)
	}
	fmt.Println()
}

func doMyParse(sql string) {
	node, err := parser.Parse(sql)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Parse error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("\n%s%s%s\n\n", tree.Dim, sql, tree.Reset)
	tree.Print(node)
	fmt.Println()
}

func doAnalyze(queries ...string) {
	// Open the catalog cache once — mirrors a Postgres backend that
	// persists its cache across all queries in a session
	dsn := os.Getenv("PGVIS_DSN")
	if dsn == "" {
		dsn = "postgresql://study:study@localhost:5433/study?sslmode=disable"
	}
	catalog, err := analyzer.OpenCatalog(dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Catalog error: %v\n", err)
		os.Exit(1)
	}
	defer catalog.Close()

	for i, sql := range queries {
		if i > 0 {
			fmt.Printf("%s────────────────────────────────────────%s\n", tree.Dim, tree.Reset)
		}

		node, err := parser.Parse(sql)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Parse error: %v\n", err)
			continue
		}

		fmt.Printf("\n%s%s%s\n\n", tree.Dim, sql, tree.Reset)
		tree.Print(node)
		fmt.Println()

		errors := analyzer.Analyze(node, catalog)

		if len(errors) == 0 {
			fmt.Printf("  %s✓ Analysis passed%s\n\n", tree.Green, tree.Reset)
		} else {
			for _, errMsg := range errors {
				fmt.Printf("  %s✗ %s%s\n", "\033[31m", errMsg, tree.Reset)
			}
			fmt.Println()
		}
	}

	catalog.DumpCache()
}

func doRewrite(sql string) {
	node, err := parser.Parse(sql)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Parse error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("\n%sBefore rewrite:%s\n\n", tree.Bold, tree.Reset)
	fmt.Printf("%s%s%s\n\n", tree.Dim, sql, tree.Reset)
	tree.Print(node)

	dsn := os.Getenv("PGVIS_DSN")
	if dsn == "" {
		dsn = "postgresql://study:study@localhost:5433/study?sslmode=disable"
	}
	rw, err := rewriter.NewRewriter(dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Rewriter error: %v\n", err)
		os.Exit(1)
	}
	defer rw.Close()

	fmt.Println()
	rewritten := rw.Rewrite(node)

	fmt.Printf("\n%sAfter rewrite:%s\n\n", tree.Bold, tree.Reset)
	tree.Print(rewritten)
	fmt.Println()
}

func doLex(sql string) {
	fmt.Printf("\n%s%s%s\n\n", tree.Dim, sql, tree.Reset)

	tokens := lexer.Tokenize(sql)
	for _, tok := range tokens {
		fmt.Printf("  %s%-12s%s  %s%-20s%s  %spos %d%s\n",
			tree.Cyan, tok.Type, tree.Reset,
			tree.Green, tok.Value, tree.Reset,
			tree.Dim, tok.Pos, tree.Reset,
		)
	}
	fmt.Println()
}
