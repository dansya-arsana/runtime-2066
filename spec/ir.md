# spec/ir.md — Semantic IR (normative)

The in-memory form between parsing and execution:

```text
Program {
    entities:  name -> Entity { columns: [Column{name, type, unique}] }
    nodes:     id -> Node { id, line, fields: name->value, inputs: [(ref, line)] }
    functions: name -> Function { name, nodes }
}
```

Normative rules:
1. Node ids are digit strings, globally unique across scopes (E104),
   at most 40 digits (E107).
2. `inputs` preserves declaration order; arity is op-specific (E207).
3. Field names are the closed set of the grammar (E102); semantics of
   each field per op is validator-enforced (spec/instructions.md).
4. Entities/columns are grammar-validated identifiers; column order is
   semantic for positional `data.insert` binding.
5. The IR is immutable after validation; execution never mutates it.
