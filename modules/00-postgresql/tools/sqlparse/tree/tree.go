package tree

import (
	"fmt"
	"io"
	"os"
	"strings"
)

const (
	Reset  = "\033[0m"
	Dim    = "\033[2m"
	Cyan   = "\033[36m"
	Yellow = "\033[33m"
	Green  = "\033[32m"
	Bold   = "\033[1m"
)

type Node struct {
	NodeType string
	Value    string
	Field    string
	Snippet  string
	Children []Node
}

func (n Node) Label() string {
	var parts []string

	if n.Field != "" {
		parts = append(parts, fmt.Sprintf("%s%s:%s", Dim, n.Field, Reset))
	}
	if n.NodeType != "" {
		parts = append(parts, fmt.Sprintf("%s%s%s", Cyan, n.NodeType, Reset))
	}
	if n.Value != "" {
		parts = append(parts, fmt.Sprintf("%s%s%s", Green, n.Value, Reset))
	}

	line := strings.Join(parts, " ")
	if n.Snippet != "" {
		line += fmt.Sprintf("  %s← %s%s", Dim, n.Snippet, Reset)
	}
	return line
}

func Print(root Node) {
	Fprint(os.Stdout, root)
}

func Fprint(w io.Writer, root Node) {
	printNode(w, root, "", true)
}

func printNode(w io.Writer, node Node, prefix string, isLast bool) {
	connector := "├── "
	childPrefix := "│   "
	if isLast {
		connector = "└── "
		childPrefix = "    "
	}

	fmt.Fprintf(w, "%s%s%s%s%s\n", prefix, Dim, connector, Reset, node.Label())

	for i, child := range node.Children {
		printNode(w, child, prefix+Dim+childPrefix+Reset, i == len(node.Children)-1)
	}
}

func Snippet(sql string, loc int) string {
	if loc < 0 || loc >= len(sql) {
		return ""
	}
	end := loc + 25
	if end > len(sql) {
		end = len(sql)
	}
	s := sql[loc:end]
	if end < len(sql) {
		s += "…"
	}
	return s
}
