# Quick Start Checklist for Next Project

**Copy this checklist to your new project's `.claude/` directory and use it as your development guide.**

---

## Project Setup

- [ ] Create `.claude/` directory in project root
- [ ] Copy `LESSONS_LEARNED.md` (comprehensive patterns)
- [ ] Copy `CODE_REVIEW_CHECKLIST.md` (for PRs)
- [ ] Copy `COMMON_PITFALLS.md` (for debugging)
- [ ] Copy this file (`QUICK_START_CHECKLIST.md`)

---

## Before Writing Code

### Architecture Phase
- [ ] Define API response format consistency
  - How will you name IDs? (run_id, employee_id, etc.)
  - Pagination structure?
  - Error response structure?
- [ ] Define error handling strategy per layer
  - Request validation (Pydantic)
  - Business rules (HTTPException)
  - Async tasks (error lists, not exceptions)
- [ ] Plan test data isolation
  - Shared test database? Document collision risk.
  - Unique ID generation strategy?
  - How will tests handle environmental constraints?

### Development Setup
- [ ] Enable type checking: `mypy --strict` in CI
- [ ] Set up linting: `pylint`, `black`, `flake8`
- [ ] Configure pre-commit hooks
- [ ] Set CI warnings threshold (0 allowed)

---

## During Development

### Every Function
- [ ] Does it have a type hint on return value?
- [ ] Does the return type match actual return value?
- [ ] If shared by multiple callers, documented calling contexts?
- [ ] If takes dict parameters, using defensive access (.get)?

### Every Endpoint
- [ ] Type hint on return? → Use Pydantic response model
- [ ] Response keys semantic? (run_id, not id)
- [ ] Error handling? → Specific HTTPException with clear message
- [ ] Test response structure? (not just status code)

### Every Async Task
- [ ] Catches all exception types that called functions raise?
- [ ] Returns structured error response, doesn't raise?
- [ ] Each item's error tracked separately? (errors list)
- [ ] Task status always SUCCESS (errors in result)?

### Every Shared Function
- [ ] Documented which contexts call it?
- [ ] Parameters defensive? (user.get("role"), not user["role"])
- [ ] Required vs optional parameters documented?
- [ ] Tested with different parameter structures?

### Every Test
- [ ] Happy path + error cases + edge cases?
- [ ] No brittle assumptions? (test accepts multiple valid outcomes)
- [ ] No flaky tests? (runs consistently)
- [ ] Error paths tested, not just success?

---

## Before Committing Code

### Code Quality
- [ ] Run: `mypy . --strict` (0 errors)
- [ ] Run: `pylint app/` (0 errors for critical issues)
- [ ] Run: `black --check app/` (formatting)
- [ ] Run: `python -m pytest tests/` (all tests pass)

### Review Against Checklist
Use `CODE_REVIEW_CHECKLIST.md`:
- [ ] Type safety checks
- [ ] Error handling checks
- [ ] Shared function design checks
- [ ] Test coverage checks
- [ ] API consistency checks

### Commit Message
- [ ] Explains WHY the change (not WHAT)
- [ ] References relevant issue/requirement
- [ ] Example: "Fix bulk upload error handling: catch HTTPException from _insert_new_employee"

---

## When Tests Fail

### Diagnose
1. Is it a code bug or test issue?
   - Run test locally: `pytest tests/test_X.py::test_Y -xvs`
   - Does it fail locally too? → Code bug
   - Only fails in CI? → Test environment/isolation issue

2. What category is it?
   - Type error? (use `COMMON_PITFALLS.md` #1)
   - API format? (use `COMMON_PITFALLS.md` #2)
   - Error handling? (use `COMMON_PITFALLS.md` #3)
   - Dictionary access? (use `COMMON_PITFALLS.md` #4)
   - Flaky test? (use `COMMON_PITFALLS.md` #6)

### Fix Order
1. **Type/code errors** - fix all at once
2. **Logic errors** - fix one by one, verify no regressions
3. **Environmental issues** - redesign test isolation

### Verify
- [ ] Run full test suite (not just changed test)
- [ ] Check CI logs for regressions
- [ ] Verify no new warnings introduced

---

## CI/CD Workflow

### CI Expectations
- Full test suite: ~1 hour
- No warnings (0 allowed)
- All tests passing
- No flaky tests

### Common CI Issues
| Issue | Cause | Fix |
|-------|-------|-----|
| ResponseValidationError | Type hint mismatch | Match type hint to actual return |
| KeyError on API response | Ambiguous key names | Use semantic names (run_id, not id) |
| Task crashes | Unhandled exception | Catch all exception types |
| Flaky test | Data collision | Make test resilient |
| Deprecation warning | Old library pattern | Migrate to new pattern |

### Debugging CI Failures
```bash
# 1. Run test locally to reproduce
pytest tests/test_X.py::test_Y -xvs

# 2. Check type hints
mypy app/ --strict

# 3. Check for deprecations
grep -r "deprecated\|Deprecated" app/

# 4. Review recent changes
git log -p -5

# 5. If still stuck, check .claude/COMMON_PITFALLS.md
```

---

## Documentation Checklist

### Code Comments
- [ ] Explain WHY, not WHAT
- [ ] Link to design decisions when non-obvious
- [ ] Document assumptions about calling contexts

### Docstrings for Shared Functions
```python
def process_entity(entity, user_context):
    """
    Process entity. Used by:
    - POST /api/entities (HTTP handler context)
    - Async task (bulk operation context)
    - Admin script (different context)
    
    Args:
        user_context: Dict with keys:
                      - username (required)
                      - role (optional, may not be present)
                      
    Raises:
        HTTPException: If duplicate entity
        ValidationError: If data invalid
    """
```

### API Documentation
- [ ] Response examples in docstring
- [ ] All response keys documented
- [ ] Error cases documented
- [ ] HTTP status codes explained

---

## Architecture Patterns to Follow

### API Response Format
```python
# Success
{"created": [...], "errors": []}           # Bulk operations
{"result": {...}, "status": "success"}     # Single operations

# Errors
{
    "created": [...],
    "errors": [{"row": 2, "reason": "..."}]  # Bulk: per-item errors
}

{"detail": "Error message"}                 # Single endpoint error
```

### Error Handling Layers
```
Layer 1: Request validation (Pydantic/FastAPI)
├─ Returns: 422 Unprocessable Entity
└─ Handled by: framework

Layer 2: Business rules (HTTPException from functions)
├─ Returns: 400/403/404 status code
└─ Handled by: endpoint exception handler

Layer 3: Async task errors (caught, added to errors list)
├─ Returns: 200 SUCCESS with errors in result
└─ Handled by: task's try/except blocks
```

### Shared Function Design
```python
# ✅ Correct pattern
def shared_function(required_param, context_dict):
    # Required: always present
    required_value = required_param
    
    # Optional: may not be present in all contexts
    optional_value = context_dict.get("optional_key")
    
    # Use carefully
    if optional_value is not None:
        do_something_with(optional_value)
```

---

## Performance & Monitoring

### Baseline Expectations
- Endpoint response time: < 500ms
- Bulk operations: async (HTTP 202)
- Long operations (>30s): always async
- Test execution: <2 hours for full suite

### Monitoring Checklist
- [ ] API response times trending up? → Query optimization needed
- [ ] Test execution time increasing? → Tests accumulating bad data
- [ ] Flaky test rate increasing? → Data isolation issue
- [ ] New warnings in CI? → Address immediately

---

## Team Communication

### When Pair Programming
1. Explain the pattern you're using
2. Reference `.claude/LESSONS_LEARNED.md` if complex
3. Call out assumptions being made
4. Verify shared function contexts

### PR Review Process
1. Use `CODE_REVIEW_CHECKLIST.md`
2. Reference specific line numbers
3. Link to design decisions in `.claude/LESSONS_LEARNED.md`
4. Don't approve if warnings are ignored

### Debugging Conversations
1. "What error are you seeing?" (get the error message)
2. "Does it happen locally?" (narrow down scope)
3. "Which category?" (refer to `COMMON_PITFALLS.md`)
4. "Have we seen this pattern before?" (check `.claude/` files)

---

## Red Flags (Stop and Review)

🚩 **Type hint says Dict but code returns List**
→ See `COMMON_PITFALLS.md` #1

🚩 **Response key is generic ("id" not "run_id")**
→ See `COMMON_PITFALLS.md` #2

🚩 **Async task only catches ValidationError**
→ See `COMMON_PITFALLS.md` #3

🚩 **Function accesses dict with ["key"] not .get("key")**
→ See `COMMON_PITFALLS.md` #4

🚩 **Deprecated library pattern in code**
→ See `COMMON_PITFALLS.md` #5

🚩 **Test fails intermittently or only in CI**
→ See `COMMON_PITFALLS.md` #6

🚩 **CI warnings allowed to accumulate**
→ See `COMMON_PITFALLS.md` #8

🚩 **Test only checks happy path, no error cases**
→ See `COMMON_PITFALLS.md` #9

---

## First Week of New Project

### Day 1
- [ ] Copy `.claude/` files to new project
- [ ] Read `LESSONS_LEARNED.md` (30 min)
- [ ] Skim `COMMON_PITFALLS.md` (20 min)

### Day 2-3
- [ ] Set up CI with type checking, linting, warnings threshold
- [ ] Design API response format (reference `LESSONS_LEARNED.md` section 2)
- [ ] Design error handling strategy (reference `LESSONS_LEARNED.md` section 8)

### Day 4-5
- [ ] Start development with checklists at hand
- [ ] Reference patterns when writing functions
- [ ] Use `CODE_REVIEW_CHECKLIST.md` before every commit

---

## Success Metrics

By the end of your project:

- [ ] 0 type checking errors (mypy --strict)
- [ ] 0 CI warnings
- [ ] 0 flaky tests
- [ ] All critical paths tested (happy + error + edge cases)
- [ ] 50%+ test coverage (ideal, not required)
- [ ] 0 generic API response keys (all semantic: run_id, employee_id, etc.)
- [ ] All async tasks handle all exception types
- [ ] All shared functions use defensive access
- [ ] All deprecation patterns migrated to current library versions

---

## Reference Documents

| Document | Use When |
|----------|----------|
| `LESSONS_LEARNED.md` | Understanding architectural patterns and design decisions |
| `CODE_REVIEW_CHECKLIST.md` | Reviewing code in PRs or before committing |
| `COMMON_PITFALLS.md` | Debugging an issue or recognizing a pattern |
| `QUICK_START_CHECKLIST.md` | Planning development workflow (this file) |

---

**Remember:** These patterns come from actual bugs in the EMS application. They're not theoretical—they're practical lessons learned through debugging and fixing issues. Apply them proactively to avoid similar problems.

**Generated from:** EMS Application Development (2026-07-17 to 2026-07-18)  
**Final State:** 314 tests passing, 0 failures, 0 flaky tests, production-ready  
**Time Saved by Following These Patterns:** ~20+ hours of debugging
