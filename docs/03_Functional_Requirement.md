# Functional Requirements

# Smart Library Management System


# 1. Introduction

This document defines the functional requirements of the Smart Library Management System. Functional requirements describe the operations, services, and features that the system must provide to its users.

# 2. Authentication Module

## FR-01: Administrator Login

### Description

The system shall allow only authorized administrators to access the application.

### Inputs

* Username
* Password

### Process

* Validate credentials.
* Verify password using secure hashing.
* Create a user session.

### Output

* Redirect to Dashboard on successful login.
* Display an error message if login fails.

## FR-02: Logout

### Description

The administrator shall be able to log out securely.

### Process

* Destroy the current session.
* Redirect to the login page.

# 3. Dashboard Module

## FR-03: Dashboard Overview

The dashboard shall display:

* Total Students
* Active Students
* Expired Students
* Today's Revenue
* Monthly Revenue
* Renewal Rate
* Pending Fees
* AI Insights

The dashboard shall update automatically based on the latest database records.

# 4. Student Management Module

## FR-04: Add Student

The administrator shall be able to add a new student.

Required information:

* Student Name
* Mobile Number
* Course/Purpose
* Shift
* Admission Date
* Membership Duration
* Fees
* Payment Status

After successful submission:

* Store the data in the database.
* Generate a Student ID.
* Display a success message.

## FR-05: View Students

The system shall display all students in a searchable table.

Features:

* Pagination
* Search
* Sorting
* Filtering

## FR-06: Edit Student

The administrator shall be able to modify student details.

Editable fields include:

* Name
* Phone Number
* Shift
* Purpose
* Fees
* Membership
* Status

## FR-07: Delete Student

The administrator shall be able to delete a student record after confirmation.

# 5. Payment Management

## FR-08: Record Payment

The administrator shall record:

* Payment Amount
* Payment Date
* Payment Method
* Remaining Balance

The system shall update payment status automatically.

## FR-09: Payment History

The system shall maintain complete payment records for every student.

# 6. Membership Module

## FR-10: Membership Tracking

The system shall automatically calculate:

* Membership Start Date
* Membership Expiry Date
* Remaining Days

Membership status:

* Active
* Expiring Soon
* Expired

# 7. Reports Module

## FR-11: Generate Reports

The administrator shall generate:

* Student Report
* Revenue Report
* Membership Report
* Payment Report

Export options:

* PDF
* Excel
* CSV

# 8. Analytics Module

## FR-12: Analytics Dashboard

The system shall display:

* Revenue Trends
* Student Growth
* Payment Distribution
* Membership Statistics
* Monthly Admissions

Charts shall be generated using Matplotlib.

# 9. Machine Learning Module

## FR-13: Renewal Prediction

The administrator shall be able to predict the renewal probability of a student.

Input Parameters:

* Purpose
* Shift
* Membership Duration
* Fees
* Previous Payment Information

Output:

* Renewal Probability
* Risk Category
* Prediction Score

# 10. Notification Module

## FR-14: Alerts

The system shall generate alerts for:

* Membership Expiry
* Pending Fees
* Low Revenue
* High-Risk Students

# 11. Settings Module

## FR-15: System Settings

The administrator shall be able to:

* Update Profile
* Change Password
* Configure System Settings

# 12. Logging Module

## FR-16: Activity Logs

The system shall record important activities such as:

* Login
* Logout
* Student Creation
* Student Update
* Student Deletion
* Payment Entry
* Report Generation

# End of Functional Requirements
