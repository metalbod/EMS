"""Course documents (PDF / Word / PowerPoint) as 'document' lessons in Course
Content — routers/ld.py: upload_course_file, replace_course_modules,
download_module_file."""
import base64
import io
import os
import zipfile

import pytest

import routers.ld as ld_module
from db import get_admin_db


def _docx_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
DOCX = _docx_bytes()
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64


def data_url(raw: bytes, mime="application/octet-stream"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


@pytest.fixture
def course(client, hr_manager_auth):
    res = client.post("/api/ld/courses", headers=hr_manager_auth,
                      json={"title": f"ZZ Files Course {os.urandom(3).hex()}", "category": "professional_development", "cost": 0})
    assert res.status_code == 201, res.text
    return res.json()


def upload(client, headers, course, name, raw):
    return client.post(f"/api/ld/courses/{course['id']}/files", headers=headers,
                       json={"file_name": name, "data_url": data_url(raw)})


def save_modules(client, headers, course, modules):
    return client.put(f"/api/ld/courses/{course['id']}/modules", headers=headers, json={"modules": modules})


def file_rows(course_id):
    conn = get_admin_db()
    try:
        return [dict(r) for r in conn.execute("SELECT id, file_name, size_bytes FROM ld_module_files WHERE course_id=? ORDER BY id", (course_id,)).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,raw,mime", [
    ("Handbook.pdf", PDF, "application/pdf"),
    ("Policy.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("Deck.pptx", DOCX, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("Old.doc", OLE, "application/msword"),
    ("Old.ppt", OLE, "application/vnd.ms-powerpoint"),
])
def test_upload_accepts_pdf_word_and_powerpoint(client, hr_manager_auth, course, name, raw, mime):
    res = upload(client, hr_manager_auth, course, name, raw)
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["file_name"], body["mime_type"], body["size_bytes"]) == (name, mime, len(raw))


@pytest.mark.parametrize("name,raw,why", [
    ("virus.exe", b"MZ\x90\x00", "extension"),
    ("notes.txt", b"hello", "extension"),
    ("fake.pdf", b"<html>not a pdf</html>", "magic bytes"),
    ("fake.docx", PDF, "magic bytes"),
    ("empty.pdf", b"", "empty"),
])
def test_upload_rejects_other_types_and_files_that_are_not_what_they_claim(client, hr_manager_auth, course, name, raw, why):
    assert upload(client, hr_manager_auth, course, name, raw).status_code == 400, why
    assert file_rows(course["id"]) == []


def test_upload_rejects_bad_base64_and_oversize(client, hr_manager_auth, course, monkeypatch):
    bad = client.post(f"/api/ld/courses/{course['id']}/files", headers=hr_manager_auth,
                      json={"file_name": "a.pdf", "data_url": "data:application/pdf;base64,@@@not-base64@@@"})
    assert bad.status_code == 400
    monkeypatch.setattr(ld_module, "LD_FILE_MAX_BYTES", 100)
    big = upload(client, hr_manager_auth, course, "big.pdf", PDF + b"x" * 200)
    assert big.status_code == 400 and "too large" in big.json()["detail"]


def test_upload_needs_the_manage_courses_permission(client, make_test_user, test_institution, course):
    token, _ = make_test_user(role="employee")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    assert upload(client, headers, course, "a.pdf", PDF).status_code == 403


def test_file_name_is_stripped_of_any_path(client, hr_manager_auth, course):
    res = upload(client, hr_manager_auth, course, "C:\\Users\\x\\..\\evil/Handbook.pdf", PDF)
    assert res.status_code == 201 and res.json()["file_name"] == "Handbook.pdf"


# ---------------------------------------------------------------------------
# Document lessons
# ---------------------------------------------------------------------------
def test_document_lesson_round_trip_and_file_count(client, hr_manager_auth, course):
    f = upload(client, hr_manager_auth, course, "Handbook.pdf", PDF).json()
    saved = save_modules(client, hr_manager_auth, course, [
        {"title": "Welcome", "content_type": "text", "content": "Hi"},
        {"title": "Handbook", "content_type": "document", "file_id": f["id"]}])
    assert saved.status_code == 200, saved.text
    doc = saved.json()[1]
    assert (doc["content_type"], doc["file_name"], doc["file_size"], doc["content"]) == ("document", "Handbook.pdf", len(PDF), None)
    assert "data" not in doc
    listed = next(c for c in client.get("/api/ld/courses", headers=hr_manager_auth).json() if c["id"] == course["id"])
    assert listed["file_count"] == 1


def test_saving_again_keeps_the_file_and_removing_the_lesson_deletes_it(client, hr_manager_auth, course):
    f = upload(client, hr_manager_auth, course, "Handbook.pdf", PDF).json()
    doc = {"title": "Handbook", "content_type": "document", "file_id": f["id"]}
    assert save_modules(client, hr_manager_auth, course, [doc]).status_code == 200
    assert save_modules(client, hr_manager_auth, course, [doc, {"title": "More", "content_type": "text", "content": "x"}]).status_code == 200
    assert [r["id"] for r in file_rows(course["id"])] == [f["id"]]          # survived two saves
    assert save_modules(client, hr_manager_auth, course, [{"title": "More", "content_type": "text", "content": "x"}]).status_code == 200
    assert file_rows(course["id"]) == []                                    # nothing links to it any more


def test_a_document_lesson_needs_a_real_file_of_the_same_course(client, hr_manager_auth, course):
    other = client.post("/api/ld/courses", headers=hr_manager_auth,
                        json={"title": f"ZZ Other {os.urandom(3).hex()}", "category": "professional_development", "cost": 0}).json()
    foreign = upload(client, hr_manager_auth, other, "x.pdf", PDF).json()
    assert save_modules(client, hr_manager_auth, course, [{"title": "A", "content_type": "document"}]).status_code == 400
    assert save_modules(client, hr_manager_auth, course, [{"title": "A", "content_type": "document", "file_id": 999999999}]).status_code == 400
    assert save_modules(client, hr_manager_auth, course, [{"title": "A", "content_type": "document", "file_id": foreign["id"]}]).status_code == 400
    assert save_modules(client, hr_manager_auth, course, [{"title": "A", "content_type": "slides"}]).status_code == 400


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
@pytest.fixture
def doc_course(client, hr_manager_auth, course):
    f = upload(client, hr_manager_auth, course, "Handbook v2.pdf", PDF).json()
    mods = save_modules(client, hr_manager_auth, course, [{"title": "Handbook", "content_type": "document", "file_id": f["id"]}]).json()
    return course, mods[0]


def enrol(client, hr, emp, course, status):
    """An enrollment for `emp` on `course`, forced to `status` directly."""
    res = client.post("/api/ld/enrollments", headers=hr, json={"course_id": course["id"], "employee_id": emp["employee_id"]})
    assert res.status_code == 201, res.text
    enr = res.json()
    conn = get_admin_db()
    try:
        conn.execute("UPDATE ld_enrollments SET status=? WHERE id=?", (status, enr["id"]))
        conn.commit()
    finally:
        conn.close()
    return enr


def test_hr_downloads_the_file_as_an_attachment_with_safe_headers(client, hr_manager_auth, doc_course):
    course, mod = doc_course
    res = client.get(f"/api/ld/modules/{mod['id']}/file", headers=hr_manager_auth)
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith("attachment;") and "Handbook%20v2.pdf" in res.headers["content-disposition"]
    assert res.headers["x-content-type-options"] == "nosniff" and "no-store" in res.headers["cache-control"]
    inline = client.get(f"/api/ld/modules/{mod['id']}/file?inline=true", headers=hr_manager_auth)
    assert inline.headers["content-disposition"].startswith("inline;")


def test_inline_is_only_honoured_for_pdf(client, hr_manager_auth, course):
    f = upload(client, hr_manager_auth, course, "Slides.pptx", DOCX).json()
    mod = save_modules(client, hr_manager_auth, course, [{"title": "S", "content_type": "document", "file_id": f["id"]}]).json()[0]
    res = client.get(f"/api/ld/modules/{mod['id']}/file?inline=true", headers=hr_manager_auth)
    assert res.headers["content-disposition"].startswith("attachment;")


def test_an_employee_needs_an_active_enrollment_to_open_the_file(client, hr_manager_auth, employee_with_login, doc_course):
    course, mod = doc_course
    emp, headers = employee_with_login(full_name="ZZ File Reader")
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers).status_code == 403     # not enrolled
    enr = enrol(client, hr_manager_auth, emp, course, "Pending Approval")
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers).status_code == 403     # not yet approved
    for status in ("In Progress", "Completed"):
        conn = get_admin_db()
        conn.execute("UPDATE ld_enrollments SET status=? WHERE id=?", (status, enr["id"])); conn.commit(); conn.close()
        res = client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers)
        assert res.status_code == 200 and res.content == PDF, status
    conn = get_admin_db()
    conn.execute("UPDATE ld_enrollments SET status='Rejected' WHERE id=?", (enr["id"],)); conn.commit(); conn.close()
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers).status_code == 403


def test_opening_the_file_marks_the_lesson_viewed_for_the_enrollee_only(client, hr_manager_auth, employee_with_login, doc_course):
    course, mod = doc_course
    emp, headers = employee_with_login(full_name="ZZ File Viewer")
    enr = enrol(client, hr_manager_auth, emp, course, "In Progress")

    def viewed(h):
        rows = client.get(f"/api/ld/courses/{course['id']}/modules?enrollment_id={enr['id']}", headers=h).json()
        return rows[0]["viewed"]

    assert viewed(hr_manager_auth) is False
    # HR opening it with someone else's enrollment id does not mark it viewed for them
    assert client.get(f"/api/ld/modules/{mod['id']}/file?enrollment_id={enr['id']}", headers=hr_manager_auth).status_code == 200
    assert viewed(hr_manager_auth) is False
    # a download without an enrollment id doesn't either
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers).status_code == 200
    assert viewed(hr_manager_auth) is False
    # the employee opening it against their own enrollment does — and repeating is harmless
    for _ in range(2):
        assert client.get(f"/api/ld/modules/{mod['id']}/file?enrollment_id={enr['id']}", headers=headers).status_code == 200
    assert viewed(hr_manager_auth) is True


def test_a_text_lesson_has_no_file_to_download(client, hr_manager_auth, course):
    mod = save_modules(client, hr_manager_auth, course, [{"title": "T", "content_type": "text", "content": "x"}]).json()[0]
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=hr_manager_auth).status_code == 404
    assert client.get("/api/ld/modules/999999999/file", headers=hr_manager_auth).status_code == 404


def test_a_manager_can_open_any_courses_file(client, make_test_user, test_institution, doc_course):
    course, mod = doc_course
    token, _ = make_test_user(role="manager")
    headers = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(test_institution["id"])}
    assert client.get(f"/api/ld/modules/{mod['id']}/file", headers=headers).status_code == 200
