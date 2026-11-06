# Engineering diagrams

Use an architecture view to explain components, ownership and connections. Use a sequence diagram for order, waiting and retries; use a state machine for legal transitions and guards. A box-and-arrow drawing cannot establish concurrency correctness or delivery guarantees.

## Evidence and diagram brief

Record the question, audience, scope and intended display size before selecting a layout. For an existing system, cite a repository revision and the code, configuration or trace that supports each component and connection. Separate implemented behavior from a proposed change. An unknown retry policy stays unknown; it does not become a convenient arrow.

Choose one meaning for each boundary: deployment unit, process, trust zone, owning team or logical subsystem. Put that meaning in the boundary label. If multiple meanings matter, use separate views. Annotate queue capacity, backpressure, blocking, persistence and acknowledgment conditions only when the material supports them. A return arrow needs its own meaning; a database icon does not prove durability.

The renderer accepts an explicit JSON specification:

| Field | Meaning |
| --- | --- |
| `title` | Nonempty, descriptive question or view title |
| `data_kind` | `observed`, `proposed` or `synthetic`; visible status banner |
| `source` | Source description, scope and relevant revision; avoid private paths in public copies |
| `rankdir` | Optional `LR` (left to right, default) or `TB` (top to bottom) |
| `font_family`, `font_size` | Optional font name and size in points; defaults `DejaVu Sans`, `11`; allowed size 9–48 |
| `boundaries` | Optional list of `{id,label}`; each node belongs to at most one boundary |
| `nodes` | Nonempty list of `{id,label,boundary?,evidence?}` |
| `edges` | List of `{from,to,label,kind,evidence?}`; endpoints are node IDs |

IDs start with a letter and then contain letters, digits, `.`, `_` or `-`. Unknown fields, duplicate IDs or edges and unknown endpoints or boundaries are rejected. `observed` requires nonempty `evidence` for every node and edge. Evidence presence is a machine check; checking that the cited material supports the diagram remains the agent's job. For a mixed current/proposed view, use `proposed` and mark the component status in its label, or draw separate views with matching IDs.

Edges use `sync` for synchronous calls, `async` for asynchronous messages, `data` for data movement and `control` for control signals. Every edge has a bracketed kind, a descriptive label and a redundant style cue. Arrow direction is sender to receiver. A queue-to-worker edge describes delivery, not necessarily a push protocol; write “poll for work” as a separate worker-to-queue call when that distinction is supported and material.

From the installed skill directory:

```bash
python3 scripts/render_architecture.py \
  --input assets/examples/architecture.json \
  --output /path/to/new-architecture-bundle
```

The bundle includes editable DOT, SVG, PDF, PNG, a caption, copied JSON and renderer, hashes and a replay command. The sample is a proposed illustrative design. Replace it with the system's own specification before describing an existing implementation. Graphviz `dot` must be on `PATH`; no Python packages or network service are needed by this renderer.

## Sequence and state views

For a short temporal interaction, keep a Mermaid source alongside its exported SVG/PDF. Preserve exact actor names and label asynchronous messages, timeouts, retries and responses. For state diagrams, label transitions as `event [guard] / action` and identify initial and terminal states. The diagram source is the editable artifact; screenshots alone are insufficient.

A small proposed sequence can be written as:

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API
    participant Q as Queue
    C->>A: Submit request
    A->>Q: Enqueue job
    Q-->>A: Enqueue acknowledgment
    A-->>C: Accepted
    Note over A,Q: Proposed behavior; acknowledgment semantics need specification
```

Do not infer an enqueue acknowledgment's persistence guarantee from its existence. Choose Mermaid, DOT or direct SVG according to the view and tools available; keep source and export versions together. For custom vectors, keep text as text and stable component IDs. Record the renderer version and font used.

## Render review

Inspect the actual export at its intended display size. Walk each source-to-target path and check arrowheads, crossings, label clearance, boundary membership, clipping and reading order. A renderer's success exit code proves that a file was created, not that the diagram is understandable. Check long labels and non-Latin glyphs after font resolution. If the graph is too wide to read in the target document, split the view or change `rankdir`; reducing text below the readable size hides the problem.

The supplied renderer does not perform automatic edge-crossing or full collision detection. It records semantic and visual reviews as pending in its manifest. Complete those reviews in the QA report after inspecting the evidence and rendered outputs. Editing DOT or SVG directly requires recording the change and regenerating downstream files and hashes; update the JSON for changes the schema can express.
