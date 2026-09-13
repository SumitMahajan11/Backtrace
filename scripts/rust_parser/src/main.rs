use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::io::{self, Read};
use syn::spanned::Spanned;
use syn::visit::Visit;
use syn::{
    Attribute, ItemEnum, ItemFn, ItemImpl, ItemMacro, ItemMod, ItemStruct, ItemTrait, ItemUse,
    UseTree,
};

#[derive(Deserialize)]
struct InputPayload {
    file_path: Option<String>,
    code_content: Option<String>,
}

#[derive(Serialize)]
struct ImportInfo {
    path: String,
    alias: String,
    is_wildcard: bool,
    raw: String,
    line_number: Option<usize>,
}

#[derive(Serialize)]
struct ModuleInfo {
    name: String,
    is_inline: bool,
    line_number: Option<usize>,
}

#[derive(Serialize)]
struct OutputPayload {
    classes: Vec<String>,
    functions: Vec<String>,
    exports: Vec<String>,
    has_main: bool,
    imports: Vec<ImportInfo>,
    modules: Vec<ModuleInfo>,
    unresolved_macros: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

struct AstVisitor {
    classes: Vec<String>,
    functions: Vec<String>,
    exports: HashSet<String>,
    has_main: bool,
    imports: Vec<ImportInfo>,
    modules: Vec<ModuleInfo>,
    unresolved_macros: HashSet<String>,
    current_impl: Option<String>,
}

impl AstVisitor {
    fn new() -> Self {
        Self {
            classes: Vec::new(),
            functions: Vec::new(),
            exports: HashSet::new(),
            has_main: false,
            imports: Vec::new(),
            modules: Vec::new(),
            unresolved_macros: HashSet::new(),
            current_impl: None,
        }
    }

    fn record_attributes(&mut self, attrs: &[Attribute]) {
        for attr in attrs {
            if let Some(ident) = attr.path().get_ident() {
                let name = ident.to_string();
                if name == "derive" {
                    self.unresolved_macros.insert("derive".to_string());
                } else {
                    self.unresolved_macros.insert(name);
                }
            }
        }
    }

    fn visit_use_tree_recursive(&mut self, prefix: &str, tree: &UseTree, line: Option<usize>) {
        match tree {
            UseTree::Path(use_path) => {
                let new_prefix = if prefix.is_empty() {
                    use_path.ident.to_string()
                } else {
                    format!("{}::{}", prefix, use_path.ident)
                };
                self.visit_use_tree_recursive(&new_prefix, &use_path.tree, line);
            }
            UseTree::Name(use_name) => {
                let full_path = if prefix.is_empty() {
                    use_name.ident.to_string()
                } else {
                    format!("{}::{}", prefix, use_name.ident)
                };
                self.imports.push(ImportInfo {
                    path: full_path.clone(),
                    alias: String::new(),
                    is_wildcard: false,
                    raw: full_path,
                    line_number: line,
                });
            }
            UseTree::Rename(use_rename) => {
                let full_path = if prefix.is_empty() {
                    use_rename.ident.to_string()
                } else {
                    format!("{}::{}", prefix, use_rename.ident)
                };
                let alias = use_rename.rename.to_string();
                self.imports.push(ImportInfo {
                    path: full_path.clone(),
                    alias: alias.clone(),
                    is_wildcard: false,
                    raw: format!("{} as {}", full_path, alias),
                    line_number: line,
                });
            }
            UseTree::Glob(_) => {
                let full_path = if prefix.is_empty() {
                    "*".to_string()
                } else {
                    format!("{}::*", prefix)
                };
                self.imports.push(ImportInfo {
                    path: full_path.clone(),
                    alias: String::new(),
                    is_wildcard: true,
                    raw: full_path,
                    line_number: line,
                });
            }
            UseTree::Group(use_group) => {
                for item in &use_group.items {
                    self.visit_use_tree_recursive(prefix, item, line);
                }
            }
        }
    }
}

impl<'ast> Visit<'ast> for AstVisitor {
    fn visit_item_use(&mut self, i: &'ast ItemUse) {
        self.record_attributes(&i.attrs);
        let line = Some(i.use_token.span().start().line);
        self.visit_use_tree_recursive("", &i.tree, line);
        syn::visit::visit_item_use(self, i);
    }

    fn visit_item_mod(&mut self, i: &'ast ItemMod) {
        self.record_attributes(&i.attrs);
        let mod_name = i.ident.to_string();
        let is_inline = i.content.is_some();
        let line = Some(i.mod_token.span().start().line);
        self.modules.push(ModuleInfo {
            name: mod_name.clone(),
            is_inline,
            line_number: line,
        });

        if matches!(i.vis, syn::Visibility::Public(_)) {
            self.exports.insert(mod_name);
        }
        syn::visit::visit_item_mod(self, i);
    }

    fn visit_item_struct(&mut self, i: &'ast ItemStruct) {
        self.record_attributes(&i.attrs);
        let struct_name = i.ident.to_string();
        self.classes.push(struct_name.clone());
        if matches!(i.vis, syn::Visibility::Public(_)) {
            self.exports.insert(struct_name);
        }
        syn::visit::visit_item_struct(self, i);
    }

    fn visit_item_enum(&mut self, i: &'ast ItemEnum) {
        self.record_attributes(&i.attrs);
        let enum_name = i.ident.to_string();
        self.classes.push(enum_name.clone());
        if matches!(i.vis, syn::Visibility::Public(_)) {
            self.exports.insert(enum_name);
        }
        syn::visit::visit_item_enum(self, i);
    }

    fn visit_item_trait(&mut self, i: &'ast ItemTrait) {
        self.record_attributes(&i.attrs);
        let trait_name = i.ident.to_string();
        self.classes.push(trait_name.clone());
        if matches!(i.vis, syn::Visibility::Public(_)) {
            self.exports.insert(trait_name);
        }
        syn::visit::visit_item_trait(self, i);
    }

    fn visit_item_fn(&mut self, i: &'ast ItemFn) {
        self.record_attributes(&i.attrs);
        let fn_name = i.sig.ident.to_string();
        if fn_name == "main" && self.current_impl.is_none() {
            self.has_main = true;
        }

        let full_fn_name = match &self.current_impl {
            Some(impl_name) => format!("{}::{}", impl_name, fn_name),
            None => fn_name.clone(),
        };

        self.functions.push(full_fn_name);
        if matches!(i.vis, syn::Visibility::Public(_)) {
            self.exports.insert(fn_name);
        }
        syn::visit::visit_item_fn(self, i);
    }

    fn visit_item_impl(&mut self, i: &'ast ItemImpl) {
        self.record_attributes(&i.attrs);
        let mut impl_type_name = None;
        if let syn::Type::Path(type_path) = &*i.self_ty {
            if let Some(segment) = type_path.path.segments.last() {
                impl_type_name = Some(segment.ident.to_string());
            }
        }

        let old_impl = self.current_impl.clone();
        self.current_impl = impl_type_name;
        syn::visit::visit_item_impl(self, i);
        self.current_impl = old_impl;
    }

    fn visit_item_macro(&mut self, i: &'ast ItemMacro) {
        if let Some(ident) = &i.ident {
            self.unresolved_macros.insert(ident.to_string());
        }
        syn::visit::visit_item_macro(self, i);
    }

    fn visit_macro(&mut self, i: &'ast syn::Macro) {
        if let Some(ident) = i.path.get_ident() {
            self.unresolved_macros.insert(ident.to_string());
        }
        syn::visit::visit_macro(self, i);
    }
}

fn main() {
    let mut input_text = String::new();
    let mut input = InputPayload {
        file_path: None,
        code_content: None,
    };

    if let Ok(_) = io::stdin().read_to_string(&mut input_text) {
        if !input_text.trim().is_empty() {
            let _ = serde_json::from_str::<InputPayload>(&input_text).map(|parsed| {
                input = parsed;
            });
        }
    }

    let args: Vec<String> = std::env::args().collect();
    if input.file_path.is_none() && args.len() > 1 {
        input.file_path = Some(args[1].clone());
    }

    let file_path = input.file_path.unwrap_or_else(|| "file.rs".to_string());
    let code_content = match input.code_content {
        Some(content) => content,
        None => match std::fs::read_to_string(&file_path) {
            Ok(c) => c,
            Err(e) => {
                output_error(&format!("failed to read file '{file_path}': {e}"));
                return;
            }
        },
    };

    let syn_file = match syn::parse_file(&code_content) {
        Ok(file) => file,
        Err(err) => {
            output_error(&format!("syntax error at line {}: {}", err.span().start().line, err));
            return;
        }
    };

    let mut visitor = AstVisitor::new();
    visitor.visit_file(&syn_file);

    let output = OutputPayload {
        classes: visitor.classes,
        functions: visitor.functions,
        exports: visitor.exports.into_iter().collect(),
        has_main: visitor.has_main,
        imports: visitor.imports,
        modules: visitor.modules,
        unresolved_macros: visitor.unresolved_macros.into_iter().collect(),
        error: None,
    };

    println!("{}", serde_json::to_string(&output).unwrap());
}

fn output_error(msg: &str) {
    let output = OutputPayload {
        classes: Vec::new(),
        functions: Vec::new(),
        exports: Vec::new(),
        has_main: false,
        imports: Vec::new(),
        modules: Vec::new(),
        unresolved_macros: Vec::new(),
        error: Some(msg.to_string()),
    };
    println!("{}", serde_json::to_string(&output).unwrap());
}
