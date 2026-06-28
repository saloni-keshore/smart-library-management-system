# Use Case Document

# Smart Library Management System

---

# 1. Introduction

This document describes the interactions between the administrator and the Smart Library Management System. Each use case represents a specific functionality provided by the application.

---

# Primary Actor

Administrator

---

# UC-01 Login

### Goal

Allow the administrator to access the system securely.

### Preconditions

* Administrator account exists.

### Main Flow

1. Open Login Page.
2. Enter username.
3. Enter password.
4. Click Login.
5. System validates credentials.
6. Dashboard is displayed.

### Alternative Flow

* Invalid credentials → Display error message.

---

# UC-02 Add Student

### Goal

Register a new student.

### Preconditions

* Administrator is logged in.

### Main Flow

1. Open Student Module.
2. Click Add Student.
3. Enter required information.
4. Click Save.
5. Student record is stored.
6. Success message displayed.

---

# UC-03 Edit Student

### Goal

Update student information.

### Main Flow

1. Search student.
2. Open student details.
3. Modify information.
4. Save changes.
5. Database updated.

---

# UC-04 Delete Student

### Goal

Remove an existing student record.

### Main Flow

1. Select student.
2. Click Delete.
3. Confirm deletion.
4. Record removed.

---

# UC-05 Record Payment

### Goal

Store student payment information.

### Main Flow

1. Open Payment Module.
2. Select student.
3. Enter payment details.
4. Save payment.
5. Update payment status.

---

# UC-06 Generate Reports

### Goal

Generate business reports.

### Main Flow

1. Open Reports.
2. Select report type.
3. Choose date range.
4. Generate report.
5. Export PDF, Excel, or CSV.

---

# UC-07 View Dashboard

### Goal

Monitor library activities.

### Main Flow

1. Login.
2. Open Dashboard.
3. View KPIs.
4. View charts.
5. Analyze business performance.

---

# UC-08 Predict Student Renewal

### Goal

Predict whether a student is likely to renew their membership.

### Main Flow

1. Open AI Prediction Module.
2. Select student.
3. System processes historical data.
4. Machine Learning model generates prediction.
5. Display renewal probability and risk category.

---

# UC-09 Receive Notifications

### Goal

Notify administrator about important events.

### Events

* Membership Expiry
* Pending Fees
* High-Risk Students
* Revenue Alerts

---

# End of Use Case Document
