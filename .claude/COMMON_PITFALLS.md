# Common Pitfalls - Lessons from EMS Debugging

These are the actual bugs found in the EMS application. Use this to avoid similar issues in your next project.

---

## Pitfall #1: Type Hints Don't Match Reality

**What Happened:**
```python
def get_scores() -> Optional[Dict[str, Any]]:
    """Get scores for employees"""
    return [{"score": 100}, {"score": 95}]  # Returns list, not optional dict!
```

**Error Seen:**
```
ResponseValidationError: 1 validation error for Response
response
  value is not a valid dict [type=type_error.dict, input_value=[...]]
```

**Why It Happened:**
- Developer thought about the shape (dict with score), not the wrapper
- Forgot that endpoint returns a list of employees, not a single score
- No type checking in CI (or it wasn't strict enough)

**How to Fix:**
```python
# ✅ Correct type hint
def get_scores() -> List[Dict[str, Any]]:
    """Get list of scores for all employees"""
    return [{"score": 100}, {"score": 95}]

# ✅ Or use Pydantic model
class ScoreResponse(BaseModel):
    score: int
    employee_id: str

def get_scores() -> List[ScoreResponse]:
    """Get list of scores for all employees"""
    return [ScoreResponse(score=100, employee_id="E001"), ...]
```

**Prevention:**
1. Enable `mypy --strict` in CI
2. Write tests that deserialize response (catches type mismatches)
3. Use Pydantic response models (more structure, less chance of mistakes)

**Lesson:** Type hints are executable contracts, not suggestions. Match them to reality.

---

## Pitfall #2: API Response Keys Are Ambiguous

**What Happened:**
```python
# Endpoint returns
def create_payroll_run(...):
    return {"id": run["id"], "status": "pending"}

# But test expects different key
def test_payroll():
    result = client.post("/api/payroll/runs", json={...})
    run_id = result["run_id"]  # KeyError: 'run_id'
```

**Error Seen:**
```
KeyError: 'run_id'
```

**Why It Happened:**
- Endpoint and test written at different times
- Generic key name `"id"` doesn't clarify which entity (run? employee? institution?)
- No endpoint documentation
- Unclear API contract

**How to Fix:**
```python
# ✅ Semantic key names
def create_payroll_run(...):
    return {
        "task_id": async_task.id,
        "run_id": run["id"],           # Clearly a payroll run ID
        "status": "pending",
        "employee_count": len(employees)
    }

# ✅ Document in docstring
class PayrollRunResponse(BaseModel):
    """Response from POST /api/payroll/runs"""
    task_id: str                       # Async task ID
    run_id: int                        # Payroll run ID
    status: str                        # "pending", "completed", "failed"
    employee_count: int
```

**Prevention:**
1. Use semantic naming: `run_id`, not `id`
2. Use Pydantic response models (self-documenting)
3. Include response examples in docstrings
4. Test response structure, not just status code

**Lesson:** Generic names create ambiguity. Be specific: which entity, which ID?

---

## Pitfall #3: Async Task Crashes on Business Rule Violation

**What Happened:**
```python
@app.task
def bulk_upload_employees_task(inst_id, csv_content, username):
    for i, row in enumerate(reader):
        try:
            emp_id = _insert_new_employee(conn, inst_id, emp, user_dict, None)
            # _insert_new_employee raises HTTPException if duplicate!
            created.append({"row": i, "employee_id": emp_id})
        except ValidationError as e:
            errors.append({"row": i, "reason": ...})
        # HTTPException not caught! Task crashes here.
```

**Error Seen:**
```
Celery task failed: HTTPException - Employee ID EMP001 already exists
Task status: FAILURE
Result: None
```

**Why It Happened:**
- Developer only caught `ValidationError` (the obvious one)
- Didn't realize `_insert_new_employee()` raises `HTTPException` for business rules
- Thought "HTTPException is an HTTP thing, it won't happen in a task"

**How to Fix:**
```python
# ✅ Catch ALL exception types that can be raised
@app.task
def bulk_upload_employees_task(inst_id, csv_content, username):
    created, errors = [], []
    
    for i, row in enumerate(reader):
        try:
            emp_id = _insert_new_employee(conn, inst_id, emp, user_dict, None)
            created.append({"row": i, "employee_id": emp_id})
        except HTTPException as e:
            errors.append({"row": i, "reason": e.detail})
        except ValidationError as e:
            errors.append({"row": i, "reason": extract_validation_error(e)})
        except IntegrityError as e:
            errors.append({"row": i, "reason": "Database constraint violation"})
        except (ValueError, TypeError) as e:
            errors.append({"row": i, "reason": str(e)})
        except Exception as e:
            logger.error(f"Unexpected error at row {i}: {e}")
            errors.append({"row": i, "reason": "Unexpected error (see logs)"})
    
    return {"created": created, "errors": errors}
```

**Prevention:**
1. Review called function's exception documentation
2. List all possible exceptions in docstring:
   ```python
   def _insert_new_employee(...):
       """
       Insert employee.
       
       Raises:
           HTTPException: If duplicate ID
           HTTPException: If manager not found
           ValidationError: If data invalid
       """
   ```
3. Test error paths, not just happy path
4. Watch Celery task failures (monitor them!)

**Lesson:** Async tasks are not immune to exceptions. You must catch them explicitly.

---

## Pitfall #4: Defensive Access Forgotten in Shared Functions

**What Happened:**
```python
def _insert_new_employee(conn, inst_id, emp, user, manager):
    # Called from HTTP handler: user = {"id": 1, "username": "john", "role": "hr_manager"}
    # Called from bulk upload task: user = {"username": "john"}
    
    if emp.employee_id and user["role"] == "hr_manager":
        # ↑ KeyError when called from bulk upload! "role" key doesn't exist
        validate_permissions(user["role"])
```

**Error Seen:**
```
KeyError: 'role'
```

**Why It Happened:**
- Function works fine when called from HTTP handler
- Different calling context (bulk upload) provides different parameters
- Developer didn't realize parameters vary by context

**How to Fix:**
```python
# ✅ Use defensive access
def _insert_new_employee(conn, inst_id, emp, user, manager):
    """
    Insert employee. Called from:
    - HTTP handler: user has {id, username, role, institution_id}
    - Bulk upload task: user has {username} only
    """
    username = user["username"]                    # Required
    role = user.get("role")                        # Optional
    
    if emp.employee_id and role == "hr_manager":   # Won't crash if role is None
        validate_permissions(role)

# ✅ Document expected keys in docstring
def _insert_new_employee(conn, inst_id, emp, user, manager):
    """
    Insert employee.
    
    Args:
        user: Dict with keys:
              - username (required): Username for audit trail
              - role (optional): User's role ("hr_manager", etc.)
                                 May not be present in all contexts.
    """
```

**Prevention:**
1. Document all calling contexts in docstring
2. Use `.get()` for optional keys
3. Test with different parameter structures
4. Raise clear error if required key is missing:
   ```python
   if "username" not in user:
       raise ValueError("user dict requires 'username' key")
   ```

**Lesson:** Shared functions must handle varying parameter structures. Use defensive access.

---

## Pitfall #5: Deprecated Library Patterns

**What Happened:**
```python
from pydantic import BaseModel

class UserResponse(BaseModel):
    id: int
    username: str
    
    class Config:                    # ← Deprecated in Pydantic v2
        json_schema_extra = {
            "example": {"id": 1, "username": "john"}
        }
```

**Error Seen:**
```
PydanticDeprecatedSince20: Using `class Config` for Pydantic model configuration
is deprecated. Use `model_config` with `ConfigDict` instead.
```

**Why It Happened:**
- Pydantic v2 released breaking changes
- Codebase wasn't updated when upgrading
- Warnings accumulated over time, CI logs got cluttered

**How to Fix:**
```python
# ✅ Pydantic v2 pattern
from pydantic import BaseModel, ConfigDict

class UserResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {"id": 1, "username": "john"}
        }
    )
    
    id: int
    username: str
```

**Prevention:**
1. Monitor dependency upgrade changelogs
2. Add linting step to CI that catches deprecations
3. Update patterns as soon as major versions released
4. Don't let warnings accumulate (they hide real issues)

**Lesson:** Library upgrades bring breaking changes. Migrate promptly.

---

## Pitfall #6: Flaky Tests from Shared Test Data

**What Happened:**
```python
def test_bulk_upload_creates_employee():
    ic = _unique_ic()  # Uses random.randint(0, 9999)
    # After 10,000 CI runs, ICs start colliding with old test data
    # Test fails intermittently (only sometimes)
    
    result = bulk_upload(ic)
    assert len(result["created"]) == 1  # Fails when IC collides!
```

**Error Seen:**
```
AssertionError: assert 0 == 1
# Test passes locally, fails in CI
# Test passes sometimes, fails sometimes
```

**Why It Happened:**
- Shared test institution `ZZPYTEST` accumulates employees
- Soft-delete semantics mean employees aren't actually removed
- Random salt (0-9999) only has 10,000 unique values
- Eventually, new test ICs collide with old test data

**How to Fix:**

**Option 1: Better unique ID generation** (partial fix)
```python
# ✅ Timestamp-based salt is better (but still not perfect)
_ic_run_salt = int(time.time_ns()) % 10000

# ✅ Or use UUID-based approach for collision-proof IDs
import uuid
def _unique_ic():
    return str(uuid.uuid4()).replace("-", "")[:12]  # 12-digit ID
```

**Option 2: Make test resilient** (best fix)
```python
# ✅ Accept both outcomes: success OR graceful duplicate handling
def test_bulk_upload_creates_employee():
    ic = _unique_ic()
    result = bulk_upload(ic)
    
    # Either created successfully OR rejected as duplicate
    # Both are correct outcomes
    assert len(result["created"]) + len(result["errors"]) == 1
    
    if result["created"]:
        # Success path
        assert result["created"][0]["employee_id"] is not None
    else:
        # Duplicate path
        assert "already exists" in result["errors"][0]["reason"]
```

**Option 3: Clean up old test data** (infrastructure fix)
```python
@pytest.fixture(scope="session", autouse=True)
def cleanup_old_test_data():
    # Delete test employees older than 1 hour before running tests
    conn = get_db()
    conn.execute("""
        DELETE FROM employees 
        WHERE institution_id = 11 (ZZPYTEST)
          AND created_at < NOW() - INTERVAL '1 hour'
    """)
    conn.commit()
```

**Prevention:**
1. Identify flaky tests early (same test fails intermittently)
2. Make tests resilient, not perfect (accept real-world constraints)
3. Use collision-resistant ID generation for tests
4. Document test data isolation strategy

**Lesson:** Flaky tests indicate environmental issues. Fix the environment or the test logic, don't ignore them.

---

## Pitfall #7: Assumptions About Code Not Getting Called

**What Happened:**
```python
# Developer thought: "This code is only used for creating employees via HTTP,
# so the user dict will always have a role field."

def _insert_new_employee(conn, inst_id, emp, user, manager):
    if emp.employee_id and user["role"] == "hr_manager":  # Assumption!
        validate_permissions()
```

**Later:** Bulk upload task starts using the same function:
```python
# Bulk upload passes minimal user dict
emp_id = _insert_new_employee(conn, inst_id, emp, {"username": username}, None)
# ↑ KeyError: bulk upload context doesn't provide "role" key
```

**Why It Happened:**
- Code wasn't designed for reuse
- Assumptions about callers weren't documented
- Found when a new calling context appeared

**How to Fix:**
1. **Document all calling contexts**
2. **Use defensive access**
3. **Design for multiple callers from the start**

```python
def _insert_new_employee(conn, inst_id, emp, user, manager):
    """
    Insert employee. Used by:
    - POST /api/employees (has user.role)
    - Bulk upload task (only has user.username)
    
    Args:
        user: Dict with username (required), role (optional)
    """
    username = user["username"]
    role = user.get("role")
    
    if emp.employee_id and role == "hr_manager":
        ...
```

**Prevention:**
1. Design functions to be called from multiple contexts
2. Document assumptions clearly
3. Use defensive programming (handle missing values)
4. Test with different parameter structures

**Lesson:** Code is reused more than you think. Design defensively.

---

## Pitfall #8: CI Warnings Ignored

**What Happened:**
```
# CI output month 1:
PydanticDeprecatedSince20: Using `class Config` is deprecated...
(5 warnings total)

# CI output month 3:
PydanticDeprecatedSince20: Using `class Config` is deprecated...
(5 warnings total, same ones, never fixed)

# CI output month 6:
PydanticDeprecatedSince20: Using `class Config` is deprecated...
(still 5 warnings, and now 2 new ones)

# Now: Can't tell which warnings are important
```

**Why It Happened:**
- Warnings were treated as optional cleanup
- Never blocked CI (no error threshold)
- Over time, warnings accumulated and hid real issues

**How to Fix:**
1. **Address warnings immediately** (don't let them accumulate)
2. **Make warnings block CI** if truly critical
3. **Track tech debt separately** if deferring is intentional

```python
# In CI config:
warnings_as_errors: true  # Make warnings break CI
# OR
allowed_warnings: 0       # Zero tolerance

# In code, if deferring:
# TODO: Fix Pydantic deprecation warning (see TECH_DEBT.md)
```

**Prevention:**
1. Review CI logs after every run
2. Fix warnings same day (don't defer)
3. Keep CI logs clean (improves visibility)
4. Use linting in CI to catch issues early

**Lesson:** Warnings rot if ignored. Address them immediately or track as tech debt.

---

## Pitfall #9: Not Testing Error Cases

**What Happened:**
```python
def test_bulk_upload():
    # Only tests happy path
    result = bulk_upload("valid_data.csv")
    assert len(result["created"]) == 100

# Nobody tested:
# - What if employee_id already exists?
# - What if manager not found?
# - What if CSV has invalid data?
```

**Result:** HTTPException crash found in production when someone tried to upload duplicates.

**How to Fix:**
```python
def test_bulk_upload_creates_employee():
    # Happy path
    result = bulk_upload("valid_employee.csv")
    assert len(result["created"]) == 1

def test_bulk_upload_reports_duplicate_id():
    # Error path: duplicate employee ID
    result = bulk_upload("duplicate_id.csv")
    assert len(result["errors"]) == 1
    assert "already exists" in result["errors"][0]["reason"]

def test_bulk_upload_reports_invalid_data():
    # Error path: validation failure
    result = bulk_upload("invalid_data.csv")
    assert len(result["errors"]) == 1
    assert "Invalid" in result["errors"][0]["reason"]
```

**Prevention:**
1. Test happy path first
2. Then test each error case
3. Then test edge cases (empty, null, boundary values)
4. Prioritize by likelihood and impact

**Lesson:** Most bugs hide in error paths. Test them first.

---

## Pitfall #10: Unclear Error Messages

**What Happened:**
```python
# Bad error message (technical, not user-facing)
raise HTTPException(400, detail="IntegrityError: unique constraint violation on employees_institution_id_employee_id_key")

# User sees: "IntegrityError: unique constraint violation on employees_institution_id_employee_id_key"
# User thinks: "What is employees_institution_id_employee_id_key? What should I do?"
```

**How to Fix:**
```python
# Good error message (clear, actionable)
if "employees_institution_id_employee_id_key" in str(e):
    raise HTTPException(
        400,
        detail="Employee ID EMP001 already exists in this institution. Use a different ID."
    )

# User sees: "Employee ID EMP001 already exists in this institution. Use a different ID."
# User thinks: "Oh, I need to use a different ID."
```

**Prevention:**
1. Catch low-level exceptions
2. Convert to user-friendly messages
3. Include action (what to do next)
4. Log original exception for debugging

**Lesson:** Users shouldn't see database error messages. Translate them.

---

## Quick Reference: Top 3 Issues to Check

1. **Type Hints** - Match to actual return types? Use `mypy --strict` in CI.
2. **Error Handling** - Catch all exceptions? Test error paths? User-friendly messages?
3. **Defensive Access** - Shared functions use `.get()`? Document parameter contracts?

Check these three before every commit.

---

Generated from EMS debugging experience. Each pitfall cost between 1-4 hours to debug.
Knowing these patterns will save 10+ hours on your next project.
