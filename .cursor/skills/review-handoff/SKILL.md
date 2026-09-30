---
name: review-handoff
description: >-
  Packages ChatGPT review material as evidence-complete dumps (verbatim files,
  tests, docs, logs, JSON, runtime evidence, Git state). Use when preparing a
  ChatGPT source review, milestone final review, read-only audit, evidence
  review, requested file dump, requested runtime evidence, or Git-state handoff.
  Does not judge implementation quality.
---

# Review Handoff

Make ChatGPT review packages **evidence-complete**. This skill does not judge implementation quality. It packages requested evidence faithfully.

Core rule:

> If ChatGPT requests file contents, test contents, docs, logs, JSON, runtime evidence, or other exact review material, Cursor MUST include the requested material itself. A summary saying the files were read does not satisfy that request.

> Never collapse an evidence package into summary-only output unless ChatGPT explicitly asked for summary-only.

A requested evidence handoff is not complete until the requested evidence itself has been returned.

## When to use

Whenever Cursor is preparing material for:

- ChatGPT source review
- milestone final review
- read-only audit
- evidence review
- requested file dumps
- requested runtime evidence
- requested Git-state handoff

## Package kinds

Distinguish these explicitly. Do not mix labels.

```text
SUMMARY HANDOFF
VERBATIM REVIEW MATERIAL
RUNTIME EVIDENCE
GIT STATE
```

When ChatGPT asks for evidence, provide the evidence first or alongside the summary.

Do not replace requested evidence with a descriptive statement.

`summary != evidence`

A normal milestone handoff may still contain a concise summary. If review evidence was requested, both may be required.

## Not a reviewer

`review-handoff` is not a reviewer. It does not judge implementation quality.

## Verbatim request rule

If ChatGPT asks for:

```text
complete exact contents
verbatim
dump the file
show the JSON
show the log
show the existing evidence
```

then:

- copy the requested material exactly;
- do not summarize instead;
- do not paraphrase;
- do not omit sections;
- do not silently clean formatting;
- do not regenerate evidence;
- do not substitute a fresh test/model run unless explicitly authorized.

A statement such as:

```text
I inspected all requested files
```

is never sufficient when contents were requested.

### Bad

```text
Files read: adapter.py, tests.py, docs.md
Everything looks good.
```

### Good

```text
===== FILE: src/.../adapter.py =====
<complete requested contents>
===== END FILE =====
```

## Output-length rule

If the requested review package is too large for one response:

1. stop only at a file/evidence boundary;
2. do not truncate a file mid-content;
3. list exactly which requested items remain;
4. continue those items in the next response when prompted.

Do not silently omit material to save space.

## Read-only review rule

For read-only review tasks, preserve the task's existing authorization boundaries.

Do not:

- edit files;
- apply patches;
- rerun tests unless explicitly authorized;
- regenerate model outputs;
- run new emulator experiments;
- commit;
- push;
- pull;
- merge;
- rebase;
- reset.

## Runtime evidence rule

If ChatGPT requests existing runtime evidence:

- return the existing textual JSON/log/output;
- do not rerun the producing process;
- do not reinterpret the values as replacements for the raw evidence;
- do not include binary data unless explicitly requested;
- clearly label runtime evidence separately from tracked files.

```text
===== RUNTIME EVIDENCE: D:\Memnara-Data\...\result.json =====

<exact existing JSON>

===== END RUNTIME EVIDENCE =====
```

## Required file format

When exact file contents are requested, default to:

```text
===== FILE: <relative path> =====

<complete exact contents>

===== END FILE =====
```

unless ChatGPT supplied another exact format.

ChatGPT's requested format takes precedence.

## Requested headings

If ChatGPT supplies required headings/status blocks, preserve them.

Do not replace them with Cursor's preferred handoff format.

Example:

If ChatGPT requests:

```text
## Response for Me
## Handoff for ChatGPT
```

use those headings.

If ChatGPT requests a final status block, reproduce it accurately.
