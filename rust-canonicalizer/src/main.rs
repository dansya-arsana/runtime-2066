// H8 spike — independent 2066 canonicalizer (plan SS36 strangler step 3).
//
// Written from spec/canonicalization.md, sharing NO code with the Python
// runtime. Reads a .ai program, re-emits its canonical form, prints
// "sha256:<hex>" of that form. Success vs the Python oracle is byte
// identity of the canonical text — compared in
// tests/independent/test_rust_canonicalizer.py when cargo is available.
//
// Spike scope (documented divergence risk): f64 rendering uses Rust's
// shortest-round-trip Debug format; exotic floats not yet proven equal
// to Python's repr. i64/bool/string canonicalization is exact.

use std::collections::BTreeMap;
use std::env;
use std::fs;

#[derive(Clone, Default)]
struct Node {
    id: String,
    numeric: u128,
    fields: BTreeMap<String, String>, // canonical set, re-ordered on emit
    inputs: Vec<String>,
}

#[derive(Clone)]
struct Column {
    name: String,
    ty: String,
    unique: bool,
}

struct Entity {
    name: String,
    columns: Vec<Column>,
}

struct Function {
    name: String,
    nodes: Vec<Node>,
}

struct Program {
    entities: Vec<Entity>,
    main_nodes: Vec<Node>,
    functions: Vec<Function>,
}

/// `#` starts a comment only OUTSIDE a quoted string (HTML/CSS colors
/// inside value strings must survive).
fn strip_comment(line: &str) -> &str {
    let mut in_string = false;
    let mut escaped = false;
    for (index, c) in line.char_indices() {
        if in_string {
            if escaped {
                escaped = false;
            } else if c == '\\' {
                escaped = true;
            } else if c == '"' {
                in_string = false;
            }
        } else if c == '"' {
            in_string = true;
        } else if c == '#' {
            return &line[..index];
        }
    }
    line
}

fn unquote_string(raw: &str) -> String {
    let body = &raw[1..raw.len() - 1];
    let mut out = String::new();
    let mut chars = body.chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('"') => out.push('"'),
                Some('\\') => out.push('\\'),
                Some(other) => out.push(other), // spike: unknown escapes pass
                None => {}
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn quote_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for c in value.chars() {
        match c {
            '\\' => escaped.push_str("\\\\"),
            '"' => escaped.push_str("\\\""),
            '\n' => escaped.push_str("\\n"),
            '\t' => escaped.push_str("\\t"),
            _ => escaped.push(c),
        }
    }
    escaped.push('"');
    escaped
}

fn canonical_value(ty: &str, raw: &str) -> String {
    match ty {
        "string" => quote_string(&unquote_string(raw)),
        "i64" => raw.parse::<i64>()
            .map(|v| v.to_string())
            .unwrap_or_else(|_| raw.to_string()),
        "bool" => raw.to_string(),
        _ => raw.to_string(), // f64 spike: Rust Debug == shortest repr
    }
}

fn parse(source: &str) -> Program {
    let mut program = Program {
        entities: Vec::new(),
        main_nodes: Vec::new(),
        functions: Vec::new(),
    };
    let mut current_entity: Option<Entity> = None;
    let mut current_node: Option<Node> = None;
    let mut current_function: Option<Function> = None;
    let mut in_main = false;

    let mut close_node = |node: &mut Option<Node>,
                          function: &mut Option<Function>,
                          main_nodes: &mut Vec<Node>| {
        if let Some(n) = node.take() {
            match function {
                Some(f) => f.nodes.push(n),
                None => main_nodes.push(n),
            }
        }
    };

    for raw_line in source.lines() {
        let line = strip_comment(raw_line).trim();
        if line.is_empty() {
            continue;
        }
        let (head, rest) = match line.find(' ') {
            Some(pos) => (&line[..pos], line[pos + 1..].trim()),
            None => (line, ""),
        };
        if std::env::var("CANON_DEBUG").is_ok() {
            eprintln!("LINE [{head}] rest=[{rest}] node={:?} func={:?} ent={:?}",
                current_node.as_ref().map(|n| n.id.clone()),
                current_function.as_ref().map(|f| f.name.clone()),
                current_entity.is_some());
        }
        match head {
            "entity" if rest.contains('{') || current_node.is_none() => {
                close_node(&mut current_node, &mut current_function,
                           &mut program.main_nodes);
                current_entity = Some(Entity {
                    name: rest.trim_end_matches('{').trim().to_string(),
                    columns: Vec::new(),
                });
            }
            "}" => {
                if let Some(entity) = current_entity.take() {
                    program.entities.push(entity);
                }
            }
            "func" => {
                close_node(&mut current_node, &mut current_function,
                           &mut program.main_nodes);
                if let Some(finished) = current_function.take() {
                    program.functions.push(finished);
                }
                current_function = Some(Function {
                    name: rest.to_string(),
                    nodes: Vec::new(),
                });
            }
            "main" => {
                close_node(&mut current_node, &mut current_function,
                           &mut program.main_nodes);
                // main CLOSES any open function scope (functions may be
                // declared before main in the source)
                if let Some(finished) = current_function.take() {
                    program.functions.push(finished);
                }
            }
            "node" => {
                close_node(&mut current_node, &mut current_function,
                           &mut program.main_nodes);
                let id = rest.to_string();
                let numeric = id.parse::<u128>().unwrap_or(0);
                current_node = Some(Node {
                    id,
                    numeric,
                    ..Default::default()
                });
            }
            "input" => {
                if let Some(node) = current_node.as_mut() {
                    node.inputs =
                        rest.split_whitespace().map(String::from).collect();
                }
            }
            "format-version" | "protocol" => { /* headers: not canonical */ }
            _ => {
                if current_entity.is_some() && current_node.is_none() {
                    // entity column: "name type [unique]" — parse the FULL
                    // line (head/rest splitting would eat the type)
                    let mut parts = line.split_whitespace();
                    let name = parts.next().unwrap_or("").to_string();
                    let ty = parts.next().unwrap_or("").to_string();
                    let unique = line.contains("unique");
                    if let Some(entity) = current_entity.as_mut() {
                        entity.columns.push(Column { name, ty, unique });
                    }
                } else if rest.is_empty() && !line.contains(' ') {
                    // bare word line inside an entity block (e.g. "}")
                    continue;
                } else if let Some(node) = current_node.as_mut() {
                    let key = if line.contains(' ') {
                        head.to_string()
                    } else {
                        line.to_string()
                    };
                    let value = if line.contains(' ') {
                        rest.to_string()
                    } else {
                        String::new()
                    };
                    if !value.is_empty() {
                        node.fields.insert(key, value);
                    }
                }
            }
        }
    }
    close_node(&mut current_node, &mut current_function,
               &mut program.main_nodes);
    if let Some(function) = current_function.take() {
        program.functions.push(function);
    }
    program
}

const FIELD_ORDER: [&str; 8] =
    ["op", "index", "type", "value", "mode", "callee", "input", "output"];

fn serialize_node(node: &Node) -> String {
    let mut lines = vec![format!("node {}", node.id)];
    for name in FIELD_ORDER {
        if name == "input" {
            if !node.inputs.is_empty() {
                lines.push(format!("input {}", node.inputs.join(" ")));
            }
        } else if let Some(raw) = node.fields.get(name) {
            let rendered = if name == "value" {
                let ty = node.fields.get("type").cloned()
                    .unwrap_or_default();
                canonical_value(&ty, raw)
            } else {
                raw.clone()
            };
            lines.push(format!("{} {}", name, rendered));
        }
    }
    lines.join("\n")
}

fn serialize(program: &Program) -> String {
    let mut entity_names: Vec<&String> =
        program.entities.iter().map(|e| &e.name).collect();
    entity_names.sort();
    let mut blocks: Vec<String> = Vec::new();
    for name in &entity_names {
        let entity = program.entities.iter()
            .find(|e| e.name == name.as_str()).unwrap();
        let mut lines = vec![format!("entity {} {{", entity.name)];
        for column in &entity.columns {
            lines.push(format!(
                "{} {}{}",
                column.name,
                column.ty,
                if column.unique { " unique" } else { "" }
            ));
        }
        lines.push("}".to_string());
        blocks.push(lines.join("\n"));
    }
    let mut main = program.main_nodes.clone();
    main.sort_by_key(|n| n.numeric);
    for node in &main {
        blocks.push(serialize_node(node));
    }
    let mut function_names: Vec<&String> =
        program.functions.iter().map(|f| &f.name).collect();
    function_names.sort();
    for name in &function_names {
        let function = program.functions.iter()
            .find(|f| f.name == name.as_str()).unwrap();
        let mut nodes = function.nodes.clone();
        nodes.sort_by_key(|n| n.numeric);
        let body: Vec<String> =
            nodes.iter().map(serialize_node).collect();
        blocks.push(
            std::iter::once(format!("func {}", function.name))
                .chain(body)
                .collect::<Vec<_>>()
                .join("\n"),
        );
    }
    if std::env::var("CANON_DEBUG").is_ok() {
        eprintln!(
            "SERIALIZE blocks={} entities={} main={} funcs={}",
            blocks.len(),
            program.entities.len(),
            program.main_nodes.len(),
            program.functions.len()
        );
    }
    let mut out = blocks.join("\n\n");
    out.push('\n');
    out
}

// ---- minimal SHA-256 (no dependencies; FIPS 180-4) --------------------

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b,
    0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7,
    0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152,
    0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f,
        0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let mut message = data.to_vec();
    let bit_len = (data.len() as u64) * 8;
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in message.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7)
                ^ w[i - 15].rotate_right(18)
                ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17)
                ^ w[i - 2].rotate_right(19)
                ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11)
                ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13)
                ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut digest = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        digest[i * 4..i * 4 + 4]
            .copy_from_slice(&word.to_be_bytes());
    }
    digest
}

fn main() {
    let path = env::args().nth(1).expect("usage: canonicalize <file.ai>");
    let source = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {path}: {e}"));
    let program = parse(&source);
    let canonical = serialize(&program);
    if env::args().any(|a| a == "--text") {
        print!("{canonical}");
        return;
    }
    let digest = sha256(canonical.as_bytes());
    println!(
        "sha256:{}",
        digest.iter().map(|b| format!("{:02x}", b)).collect::<String>()
    );
}
