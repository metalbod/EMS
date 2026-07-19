# Code Review Checklist - Lessons from EMS

Use this checklist when reviewing code for the next project. These checks prevented ~16 bugs in the EMS application.

## API & Type Safety ✅

- [ ] **All endpoints have return type hints**
  - Route handler returns typed `Dict`, `List`, `ModelResponse`, etc.
  - Type matches actual return value (not assumed)
  - Example issue: `def get_scores() -> Dict` but returns `List` → ResponseValidationError

- [ ] **Response keys are semantic, not generic**
  - ✅ `run_id`, `employee_id`, `institution_id` (clearly which entity)
  - ❌ `id`, `data`, `value` (ambiguous which entity)
  - Example issue: Changed `"id"` to `"run_id"` in payroll endpoint

- [ ] **Pydantic response models used for complex types**
  - ✅ `class TokenResponse(BaseModel): access_token: str; user: dict`
  - ❌ `Dict[str, Any]` for complex responses (loses type info)

- [ ] **ConfigDict pattern used (Pydantic v2)**
  - ✅ `model_config = ConfigDict(json_schema_extra={...})`
  - ❌ `class Config:` (deprecated v1 pattern)
  - Check all model definitions for deprecation warnings

---

## Error Handling ✅

- [ ] **Specific exceptions, not generic Exception**
  - ✅ `raise HTTPException(400, detail="User not found")`
  - ❌ `raise Exception("error")`

- [ ] **All exception types from called functions identified and caught**
  - Example: `_insert_new_employee()` raises `HTTPException` for duplicates
  - Async tasks must catch ALL exception types: `ValidationError`, `HTTPException`, `IntegrityError`, `ValueError`, `TypeError`
  - Issue found: HTTPException wasn't caught in bulk_upload_employees_task

- [ ] **Error messages are user-facing and actionable**
  - ✅ `"Employee ID already exists in this institution"`
  - ❌ `"IntegrityError: unique constraint violation on employees_institution_id_employee_id_key"`

- [ ] **Original exception logged for debugging**
  - ✅ Log the exception → display friendly message to user
  - ❌ Swallow exception without logging

---

## Shared Function Design ✅

- [ ] **Functions document their parameter contracts**
  ```python
  def _insert_new_employee(conn, inst_id, emp, user, manager):
      """
      Args:
          user: Dict with keys: username (required), role (optional).
                Different contexts provide different keys.
      """
  ```

- [ ] **Defensive dictionary access for parameters**
  - ✅ `user.get("role")` in shared functions (handles missing keys)
  - ❌ `user["role"]` in shared functions (crashes if not present)
  - Example issue: Bulk upload context provides `{"username": ...}` without `role`

- [ ] **Different calling contexts documented**
  - HTTP endpoint context: `user` has all auth fields
  - Async task context: `user` has only `username`
  - Admin function context: `user` might be minimal

---

## Async Task Robustness ✅

- [ ] **Task doesn't crash on individual item failures**
  - ✅ Bulk operations return `{"created": [...], "errors": [...]}`
  - ❌ Bulk operations crash if one item fails

- [ ] **Per-item error tracking**
  ```python
  errors = []
  for i, item in enumerate(items):
      try:
          process(item)
      except Exception as e:
          errors.append({"row": i, "reason": str(e)})
  ```

- [ ] **Task status always returns SUCCESS (errors in result, not exception)**
  - Celery task result: `{"created": [...], "errors": [...]}`
  - Don't raise from task unless unrecoverable

---

## Testing ✅

- [ ] **Critical path tested**
  - Happy path (success case)
  - Error cases (validation, permissions, duplicates)
  - Edge cases (empty list, null values, boundaries)

- [ ] **No brittle test assumptions**
  - ❌ Test assumes IC never collides (brittle)
  - ✅ Test accepts IC collision OR success (resilient)
  - Example: `assert len(created) + len(errors) == 1` (either outcome is correct)

- [ ] **Test data isolation documented**
  - Comment if tests share data across runs
  - Document collision risk
  - Document how resilience works

- [ ] **No flaky tests**
  - Same test doesn't fail intermittently
  - Doesn't work locally but fail in CI
  - Doesn't fail when run in parallel
  - If flaky: redesign, don't ignore

---

## Documentation ✅

- [ ] **Comments explain WHY, not WHAT**
  - ✅ `# Collision risk from data accumulation, but task handles gracefully`
  - ❌ `# Generate IC number` (code already shows what)

- [ ] **Commit messages document decisions**
  ```
  Fix bulk upload error handling: catch HTTPException
  
  The task calls _insert_new_employee which raises HTTPException
  for business rule violations. Without catching it, entire task
  fails. Now we add to errors list instead.
  ```

- [ ] **Non-obvious patterns documented**
  - Soft-delete semantics
  - Shared test data strategy
  - Why this architecture vs alternatives

---

## Deprecation & Dependencies ✅

- [ ] **No deprecated patterns in code**
  - Pydantic v2: `ConfigDict`, not `Config` class
  - Other libraries: check major version docs

- [ ] **CI warnings reviewed**
  - Are they code-related or external?
  - Are they actually warnings or just noise?
  - Is tech debt tracked if deferred?

- [ ] **Type checking runs without errors**
  - `mypy app/ --strict` passes
  - Or at least `mypy app/` without strict mode

---

## API Consistency ✅

- [ ] **Response structure consistent across endpoints**
  ```python
  # All list endpoints return same structure
  GET /api/employees → {"data": [...], "total": N, "page": 1}
  GET /api/payroll/runs → {"data": [...], "total": N, "page": 1}
  
  # All create endpoints return same structure
  POST /api/employees → {"employee_id": "...", "full_name": "..."}
  POST /api/payroll → {"run_id": 123, "status": "pending"}
  ```

- [ ] **HTTP status codes consistent**
  - 200: Success with response body
  - 201: Resource created
  - 202: Accepted for async operations
  - 400: Invalid request (client error)
  - 401: Unauthorized
  - 403: Forbidden (authorized but not allowed)
  - 404: Not found
  - 422: Unprocessable entity (validation failed)

- [ ] **Pagination consistent if implemented**
  ```python
  {
    "data": [...],
    "total": N,
    "page": 1,
    "page_size": 20,
    "total_pages": 5
  }
  ```

---

## Performance & Scaling ✅

- [ ] **Long operations use async (HTTP 202, Celery)**
  - Payroll calculation: async task
  - Bulk employee upload: async task
  - Keep endpoint response time < 500ms

- [ ] **Database indexes on frequently queried fields**
  - Foreign keys
  - Status fields (Active, Inactive)
  - Dates used in filtering

- [ ] **N+1 queries prevented**
  - Use eager loading if accessing relationships
  - Document if batch operations are intentional

---

## Questions to Ask During Review

1. **Type Hints:** Could I understand return types without reading the implementation?
2. **Errors:** What exceptions can this function raise? Are they caught by callers?
3. **Sharing:** Is this function called from multiple contexts? Are parameters defensive?
4. **Tests:** Would I know if this code was broken? Is the test brittle or resilient?
5. **Documentation:** Can someone maintain this code in 6 months without reading the implementation?
6. **Consistency:** Does this follow the same pattern as similar code in the codebase?

---

**Use this checklist for PRs, code reviews, and before committing code.**

Generated from EMS application review. 314 tests passing, 0 failures.
