/**
 * Node.js helper script for JavaScript/TypeScript AST structural parsing.
 * Invoked by app/parser/javascript_parser.py via subprocess stdin/stdout.
 */

const babelParser = require('@babel/parser');
const traverse = require('@babel/traverse').default;

function parseJS(code, filePath) {
  const isTS = filePath.endsWith('.ts') || filePath.endsWith('.tsx');
  const isJSX = filePath.endsWith('.jsx') || filePath.endsWith('.tsx');

  const plugins = [
    'asyncGenerators',
    'bigInt',
    'classProperties',
    'classPrivateProperties',
    'classPrivateMethods',
    'decorators-legacy',
    'doExpressions',
    'dynamicImport',
    'exportDefaultFrom',
    'exportNamespaceFrom',
    'functionBind',
    'functionSent',
    'importMeta',
    'nullishCoalescingOperator',
    'numericSeparator',
    'objectRestSpread',
    'optionalCatchBinding',
    'optionalChaining',
    'throwExpressions',
  ];

  if (isTS) plugins.push('typescript');
  if (isJSX) plugins.push('jsx');

  let ast;
  try {
    ast = babelParser.parse(code, {
      sourceType: 'unambiguous',
      plugins: plugins,
      errorRecovery: false,
    });
  } catch (err) {
    return {
      error: err.message,
      line: err.loc ? err.loc.line : null,
      column: err.loc ? err.loc.column : null,
    };
  }

  const classes = [];
  const functions = [];
  const exportsList = [];
  const imports = [];

  traverse(ast, {
    ClassDeclaration(path) {
      if (path.node.id && path.node.id.name) {
        classes.push(path.node.id.name);
      }
    },
    FunctionDeclaration(path) {
      if (path.node.id && path.node.id.name) {
        functions.push(path.node.id.name);
      }
    },
    VariableDeclarator(path) {
      if (
        path.node.id &&
        path.node.id.type === 'Identifier' &&
        path.node.init &&
        (path.node.init.type === 'ArrowFunctionExpression' ||
          path.node.init.type === 'FunctionExpression')
      ) {
        functions.push(path.node.id.name);
      }
    },
    ExportNamedDeclaration(path) {
      if (path.node.declaration) {
        if (path.node.declaration.id && path.node.declaration.id.name) {
          exportsList.push(path.node.declaration.id.name);
        } else if (path.node.declaration.declarations) {
          for (const decl of path.node.declaration.declarations) {
            if (decl.id && decl.id.name) exportsList.push(decl.id.name);
          }
        }
      }
      if (path.node.specifiers) {
        for (const spec of path.node.specifiers) {
          if (spec.exported && spec.exported.name) {
            exportsList.push(spec.exported.name);
          }
        }
      }
      if (path.node.source) {
        const specifier = path.node.source.value;
        const line = path.node.loc ? path.node.loc.start.line : null;
        imports.push({
          specifier: specifier,
          category: 'wildcard',
          import_type: 'star',
          raw: code.substring(path.node.start, path.node.end),
          line_number: line,
        });
      }
    },
    ExportAllDeclaration(path) {
      if (path.node.source) {
        const specifier = path.node.source.value;
        const line = path.node.loc ? path.node.loc.start.line : null;
        imports.push({
          specifier: specifier,
          category: 'wildcard',
          import_type: 'star',
          raw: code.substring(path.node.start, path.node.end),
          line_number: line,
        });
      }
    },
    ImportDeclaration(path) {
      const specifier = path.node.source.value;
      const line = path.node.loc ? path.node.loc.start.line : null;

      let cat = 'static';
      let impType = 'static';

      const hasNamespace = path.node.specifiers.some(
        (s) => s.type === 'ImportNamespaceSpecifier'
      );
      if (hasNamespace) {
        cat = 'wildcard';
        impType = 'star';
      }

      imports.push({
        specifier: specifier,
        category: cat,
        import_type: impType,
        raw: code.substring(path.node.start, path.node.end),
        line_number: line,
      });
    },
    CallExpression(path) {
      // require('specifier')
      if (
        path.node.callee.type === 'Identifier' &&
        path.node.callee.name === 'require' &&
        path.node.arguments.length > 0 &&
        path.node.arguments[0].type === 'StringLiteral'
      ) {
        const specifier = path.node.arguments[0].value;
        const line = path.node.loc ? path.node.loc.start.line : null;
        imports.push({
          specifier: specifier,
          category: 'static',
          import_type: 'static',
          raw: code.substring(path.node.start, path.node.end),
          line_number: line,
        });
      }
      // import('specifier') dynamic import
      if (
        path.node.callee.type === 'Import' &&
        path.node.arguments.length > 0 &&
        path.node.arguments[0].type === 'StringLiteral'
      ) {
        const specifier = path.node.arguments[0].value;
        const line = path.node.loc ? path.node.loc.start.line : null;
        imports.push({
          specifier: specifier,
          category: 'dynamic',
          import_type: 'dynamic',
          raw: code.substring(path.node.start, path.node.end),
          line_number: line,
        });
      }
    },
  });

  return {
    classes,
    functions,
    exports: exportsList,
    imports,
  };
}

let inputData = '';
process.stdin.on('data', (chunk) => {
  inputData += chunk;
});
process.stdin.on('end', () => {
  try {
    const payload = JSON.parse(inputData);
    const result = parseJS(payload.code_content, payload.file_path);
    console.log(JSON.stringify(result));
  } catch (err) {
    console.log(JSON.stringify({ error: err.message }));
  }
});
