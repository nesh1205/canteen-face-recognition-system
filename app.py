from flask import Flask, render_template, request, redirect, url_for, session, Response
import json
import os

import cv2
from deepface import DeepFace
from datetime import datetime

import csv
from io import StringIO

import pandas as pd


app = Flask(__name__)
app.secret_key = "demo_secret_key"

DATA_DIR = "data"


def load_json(filename):
    with open(os.path.join(DATA_DIR, filename), "r") as file:
        return json.load(file)


def save_json(filename, data):
    with open(os.path.join(DATA_DIR, filename), "w") as file:
        json.dump(data, file, indent=4)


def login_required():
    if "user" not in session:
        return redirect(url_for("login"))
    return None


def role_required(roles):
    check = login_required()
    if check:
        return check

    if session["user"]["role"] not in roles:
        return "Access denied"

    return None


@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        users = load_json("users.json")

        for user in users:
            if user["email"] == email and user["password"] == password:
                session["user"] = user

                if user["role"] == "canteen":
                    return redirect(url_for("kiosk"))

                return redirect(url_for("dashboard"))

        error = "Invalid email or password"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    check = role_required(["admin", "hr"])
    if check:
        return check

    employees = load_json("employees.json")
    meal_records = load_json("meal_records.json")

    return render_template(
        "dashboard.html",
        total_employees=len(employees),
        total_records=len(meal_records)
    )


@app.route("/employees")
def employees():
    check = role_required(["admin", "hr"])
    if check:
        return check

    employees_list = load_json("employees.json")
    
    # Get search parameters
    employee_id = request.args.get('employee_id', '').strip()
    name = request.args.get('name', '').strip()
    
    # Filter employees based on search criteria
    if employee_id:
        employees_list = [e for e in employees_list if employee_id.lower() in str(e.get('employee_id', '')).lower()]
    
    if name:
        employees_list = [e for e in employees_list if name.lower() in e.get('name', '').lower()]
    
    return render_template("employees.html", employees=employees_list)


@app.route("/kiosk")
def kiosk():
    check = role_required(["admin", "canteen"])
    if check:
        return check

    sessions = load_json("meal_sessions.json")
    return render_template("kiosk.html", sessions=sessions)


@app.route("/meal_records")
def meal_records():
    check = role_required(["admin", "hr"])
    if check:
        return check

    records = load_json("meal_records.json")
    return render_template("meal_records.html", records=records)

@app.route("/scan_face")
def scan_face():
    check = role_required(["admin", "canteen"])
    if check:
        return check

    employees = load_json("employees.json")
    meal_records = load_json("meal_records.json")

    temp_image_path = "static/temp_scan.jpg"
    face_folder = "static/employee_faces"

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        return "Camera not found"

    captured = False

    while True:
        ret, frame = camera.read()

        if not ret:
            break

        cv2.imshow("Scan Face - Press SPACE to Scan, ESC to Cancel", frame)

        key = cv2.waitKey(1)

        if key == 32:
            cv2.imwrite(temp_image_path, frame)
            captured = True
            break

        if key == 27:
            break

    camera.release()
    cv2.destroyAllWindows()

    if not captured:
        return render_template(
            "scan_result.html",
            message="Face scan cancelled.",
            message_type="warning",
            employee=None
        )

    matched_employee = None

    for employee in employees:
        if employee.get("status") != "active":
            continue

        face_image = employee.get("face_image")
        if not face_image:
            continue

        registered_face_path = os.path.join(face_folder, face_image)

        if not os.path.exists(registered_face_path):
            continue

        try:
            result = DeepFace.verify(
                img1_path=temp_image_path,
                img2_path=registered_face_path,
                model_name="ArcFace",
                enforce_detection=False
            )

            if result["verified"]:
                matched_employee = employee
                break

        except Exception:
            continue

    if not matched_employee:
        return render_template(
            "scan_result.html",
            message="Face not recognized.",
            message_type="danger",
            employee=None
        )

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    sessions = load_json("meal_sessions.json")
    active_session = None

    for meal_session in sessions:
        if meal_session["start_time"] <= current_time <= meal_session["end_time"]:
            active_session = meal_session
            break

    if not active_session:
        return render_template(
            "scan_result.html",
            message=f"{matched_employee['name']} recognized, but no active meal session now.",
            message_type="warning",
            employee=matched_employee
        )

    for record in meal_records:
        if (
            record["employee_id"] == matched_employee["employee_id"]
            and record["date"] == today
            and record["session"] == active_session["session_name"]
        ):
            return render_template(
                "scan_result.html",
                message=f"{matched_employee['name']} already recorded for {active_session['session_name']} today.",
                message_type="warning",
                employee=matched_employee
            )

    new_record = {
        "employee_id": matched_employee["employee_id"],
        "name": matched_employee["name"],
        "session": active_session["session_name"],
        "date": today,
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "taken"
    }

    meal_records.append(new_record)
    save_json("meal_records.json", meal_records)

    return render_template(
        "scan_result.html",
        message=f"{matched_employee['name']} recorded successfully for {active_session['session_name']}.",
        message_type="success",
        employee=matched_employee
    )

@app.route("/export_meal_records")
def export_meal_records():
    check = role_required(["admin", "hr"])
    if check:
        return check

    records = load_json("meal_records.json")

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Employee ID",
        "Name",
        "Session",
        "Date",
        "Date Time",
        "Status"
    ])

    for record in records:
        writer.writerow([
            record.get("employee_id", ""),
            record.get("name", ""),
            record.get("session", ""),
            record.get("date", ""),
            record.get("datetime", ""),
            record.get("status", "")
        ])

    response = Response(
        output.getvalue(),
        mimetype="text/csv"
    )

    response.headers["Content-Disposition"] = "attachment; filename=meal_records.csv"

    return response

@app.route("/import_employees", methods=["GET", "POST"])
def import_employees():
    check = role_required(["admin", "hr"])
    if check:
        return check

    message = None
    message_type = None

    if request.method == "POST":
        file = request.files["file"]

        if file.filename == "":
            message = "Please select an Excel file."
            message_type = "danger"
        else:
            df = pd.read_excel(file)

            employees = []

            for _, row in df.iterrows():
                employee = {
                    "employee_id": str(row["employee_id"]).strip(),
                    "name": str(row["name"]).strip(),
                    "department": str(row["department"]).strip(),
                    "position": str(row["position"]).strip(),
                    "face_image": str(row["face_image"]).strip(),
                    "status": str(row["status"]).strip().lower()
                }

                employees.append(employee)

            save_json("employees.json", employees)

            message = f"{len(employees)} employees imported successfully."
            message_type = "success"

    return render_template(
        "import_employees.html",
        message=message,
        message_type=message_type
    )


if __name__ == "__main__":
    app.run(debug=True)