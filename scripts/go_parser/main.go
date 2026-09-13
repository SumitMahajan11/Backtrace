package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"os"
	"strings"
	"unicode"
)

type InputPayload struct {
	FilePath    string `json:"file_path"`
	CodeContent string `json:"code_content"`
}

type ImportInfo struct {
	Path       string `json:"path"`
	Alias      string `json:"alias"`
	IsBlank    bool   `json:"is_blank"`
	IsDot      bool   `json:"is_dot"`
	IsGrouped  bool   `json:"is_grouped"`
	LineNumber int    `json:"line_number"`
	Raw        string `json:"raw"`
}

type OutputPayload struct {
	Package   string       `json:"package"`
	Classes   []string     `json:"classes"`
	Functions []string     `json:"functions"`
	Exports   []string     `json:"exports"`
	HasMain   bool         `json:"has_main"`
	Imports   []ImportInfo `json:"imports"`
	Error     string       `json:"error,omitempty"`
}

func main() {
	var input InputPayload

	stat, _ := os.Stdin.Stat()
	if (stat.Mode() & os.ModeCharDevice) == 0 {
		data, err := io.ReadAll(os.Stdin)
		if err == nil && len(data) > 0 {
			_ = json.Unmarshal(data, &input)
		}
	}

	if input.FilePath == "" && len(os.Args) > 1 {
		input.FilePath = os.Args[1]
	}

	if input.FilePath == "" && input.CodeContent == "" {
		outputError("no file path or code content provided")
		return
	}

	fset := token.NewFileSet()
	var node *ast.File
	var err error

	if input.CodeContent != "" {
		node, err = parser.ParseFile(fset, input.FilePath, input.CodeContent, parser.ParseComments)
	} else {
		node, err = parser.ParseFile(fset, input.FilePath, nil, parser.ParseComments)
	}

	if err != nil {
		outputError(err.Error())
		return
	}

	out := OutputPayload{
		Package:   node.Name.Name,
		Classes:   make([]string, 0),
		Functions: make([]string, 0),
		Exports:   make([]string, 0),
		Imports:   make([]ImportInfo, 0),
	}

	exportMap := make(map[string]bool)

	// Traverse AST declarations
	for _, decl := range node.Decls {
		switch d := decl.(type) {
		case *ast.GenDecl:
			// Process imports and type declarations (structs)
			isGrouped := d.Lparen.IsValid()
			for _, spec := range d.Specs {
				switch s := spec.(type) {
				case *ast.ImportSpec:
					impPath := strings.Trim(s.Path.Value, "\"")
					alias := ""
					isBlank := false
					isDot := false
					raw := s.Path.Value

					if s.Name != nil {
						alias = s.Name.Name
						raw = fmt.Sprintf("%s %s", alias, s.Path.Value)
						if alias == "_" {
							isBlank = true
						} else if alias == "." {
							isDot = true
						}
					}

					line := fset.Position(s.Pos()).Line
					out.Imports = append(out.Imports, ImportInfo{
						Path:       impPath,
						Alias:      alias,
						IsBlank:    isBlank,
						IsDot:      isDot,
						IsGrouped:  isGrouped,
						LineNumber: line,
						Raw:        raw,
					})

					if isExported(impPath) {
						exportMap[impPath] = true
					}

				case *ast.TypeSpec:
					typeName := s.Name.Name
					out.Classes = append(out.Classes, typeName)
					if isExported(typeName) {
						exportMap[typeName] = true
					}

				case *ast.ValueSpec:
					for _, name := range s.Names {
						if isExported(name.Name) {
							exportMap[name.Name] = true
						}
					}
				}
			}

		case *ast.FuncDecl:
			funcName := d.Name.Name
			fullFuncName := funcName

			if d.Recv != nil && len(d.Recv.List) > 0 {
				recvType := ""
				switch t := d.Recv.List[0].Type.(type) {
				case *ast.Ident:
					recvType = t.Name
				case *ast.StarExpr:
					if ident, ok := t.X.(*ast.Ident); ok {
						recvType = ident.Name
					}
				}
				if recvType != "" {
					fullFuncName = fmt.Sprintf("%s.%s", recvType, funcName)
				}
			} else {
				// Top level function
				if node.Name.Name == "main" && funcName == "main" {
					out.HasMain = true
				}
			}

			out.Functions = append(out.Functions, fullFuncName)
			if isExported(funcName) {
				exportMap[funcName] = true
			}
		}
	}

	for exp := range exportMap {
		out.Exports = append(out.Exports, exp)
	}

	resp, _ := json.Marshal(out)
	fmt.Println(string(resp))
}

func isExported(name string) bool {
	if len(name) == 0 {
		return false
	}
	r := rune(name[0])
	return unicode.IsUpper(r)
}

func outputError(msg string) {
	out := OutputPayload{Error: msg}
	resp, _ := json.Marshal(out)
	fmt.Println(string(resp))
}
