# MCPbox Development Methodology

This document defines the consistent workflow for developing MCPbox. Follow this process for all feature work.

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEVELOPMENT WORKFLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. PLANNING PHASE                                                           │
│     └─► Define Epics (large features, ~1-4 weeks of work)                   │
│         └─► Break Epic into Tasks (< 1 day of work each)                    │
│             └─► Define acceptance criteria for each task                    │
│                                                                              │
│  2. IMPLEMENTATION PHASE                                                     │
│     └─► Pick next task from current Epic                                    │
│         └─► Write code (tests alongside or immediately after)               │
│             └─► Verify acceptance criteria met                              │
│                 └─► Commit with descriptive message                         │
│                     └─► Mark task complete, pick next                       │
│                                                                              │
│  3. INTEGRATION PHASE                                                        │
│     └─► All tasks in Epic complete                                          │
│         └─► Integration testing                                             │
│             └─► Update documentation if needed                              │
│                 └─► Mark Epic complete                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Epic Definition

An Epic is a large feature that delivers user-facing value. Each Epic should:

- Have a clear **goal** (what user problem does it solve?)
- Be **decomposable** into 5-20 tasks
- Be **demonstrable** (you can show it working when done)
- Take roughly **1-4 weeks** to complete

### Epic Template

```markdown
## Epic N: [Title]

**Goal:** [One sentence describing the user-facing outcome]

**Success Criteria:**
- [ ] [Measurable outcome 1]
- [ ] [Measurable outcome 2]
- [ ] [Measurable outcome 3]

**Dependencies:** [Other epics or external factors]

**Out of Scope:** [Explicitly excluded items]
```

## Task Definition

A Task is a discrete unit of work that can be completed in **< 1 day**. Each Task should:

- Be **atomic** (makes sense on its own)
- Have clear **acceptance criteria** (how do we know it's done?)
- Be **testable** (can write tests for it)
- Result in a **commit** (or small set of commits)

### Task Template

```markdown
### Task N.M: [Title]

**Description:** [What needs to be done]

**Acceptance Criteria:**
- [ ] [Specific, verifiable criterion 1]
- [ ] [Specific, verifiable criterion 2]

**Files to Create/Modify:**
- `path/to/file.py` - [what changes]

**Tests:**
- [ ] [Test case 1]
- [ ] [Test case 2]
```

## Task States

| State | Meaning |
|-------|---------|
| `pending` | Not started |
| `in_progress` | Currently being worked on (max 1 at a time) |
| `blocked` | Cannot proceed, needs input or dependency |
| `completed` | Done and verified |
| `skipped` | Decided not to do (with reason) |

## Commit Convention

Follow conventional commits:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat` - New feature
- `fix` - Bug fix
- `refactor` - Code change that neither fixes a bug nor adds a feature
- `test` - Adding or updating tests
- `docs` - Documentation only
- `chore` - Build process, dependencies, etc.

Examples:
```
feat(backend): add server CRUD endpoints
fix(sandbox): handle container crash recovery
test(api): add integration tests for builder endpoints
```

## File Organization

```
docs/
├── ARCHITECTURE.md      # System design (already exists)
├── EPICS.md             # Epic definitions and status
└── TASKS/
    ├── EPIC-01.md       # Task breakdown for Epic 1
    ├── EPIC-02.md       # Task breakdown for Epic 2
    └── ...
```

## Quality Gates

Before marking a task complete:

1. **Code compiles/runs** without errors
2. **Tests pass** (if applicable)
3. **Linting passes** (if configured)
4. **Acceptance criteria verified**
5. **Committed** with proper message

Before marking an Epic complete:

1. **All tasks complete** (or explicitly skipped)
2. **Integration tested** (features work together)
3. **Documentation updated** (if user-facing changes)
4. **Demo-ready** (can show it working)

## When to Deviate

This methodology is a guide, not a straitjacket. Deviate when:

- A task turns out to be much larger → Split it
- A task is trivial → Combine with related task
- New requirements emerge → Add tasks, update Epic
- Blocked on external factor → Mark blocked, work on something else

Always document deviations in the task/epic notes.
