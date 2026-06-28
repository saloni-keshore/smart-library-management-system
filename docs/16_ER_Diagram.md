# ER Diagram

# Smart Library Management System

---

# 1. Introduction

This document describes the Entity Relationship (ER) model of the Smart Library Management System. The ER model illustrates how different entities are related within the database.

---

# 2. Main Entities

The database consists of the following entities:

* Admin
* Student
* Membership
* Payment
* Prediction
* Notification
* Activity Log

---

# 3. Entity Descriptions

## Admin

Stores administrator information.

Primary Key:

admin_id

Relationship:

One Admin can perform many activities.

---

## Student

Stores student information.

Primary Key:

student_id

Relationship:

One Student can have:

* One Membership
* Many Payments
* Many Predictions
* Many Notifications

---

## Membership

Stores membership details.

Primary Key:

membership_id

Foreign Key:

student_id

Relationship:

One Membership belongs to one Student.

---

## Payment

Stores payment transactions.

Primary Key:

payment_id

Foreign Key:

student_id

Relationship:

Many Payments belong to one Student.

---

## Prediction

Stores Machine Learning predictions.

Primary Key:

prediction_id

Foreign Key:

student_id

Relationship:

Many Predictions belong to one Student.

---

## Notification

Stores alerts.

Primary Key:

notification_id

Foreign Key:

student_id

Relationship:

Many Notifications belong to one Student.

---

## Activity Log

Stores administrator activities.

Primary Key:

log_id

Foreign Key:

admin_id

Relationship:

Many Activity Logs belong to one Admin.

---

# 4. ER Diagram (Conceptual)

```
                 +-------------+
                 |   Admin     |
                 +-------------+
                 | admin_id PK |
                 | name        |
                 | username    |
                 | password    |
                 +-------------+
                        |
                        | 1
                        |
                        | N
                 +------------------+
                 | Activity Logs    |
                 +------------------+
                 | log_id PK        |
                 | admin_id FK      |
                 | action           |
                 | module           |
                 | timestamp        |
                 +------------------+


                 +----------------+
                 |   Student      |
                 +----------------+
                 | student_id PK  |
                 | name           |
                 | mobile         |
                 | purpose        |
                 | shift          |
                 +----------------+
                      |
       ---------------------------------------
       |             |            |          |
      1|            N|           N|         N|
       |             |            |          |
+---------------+ +-----------+ +-------------+ +---------------+
| Membership    | | Payments  | | Prediction  | | Notification  |
+---------------+ +-----------+ +-------------+ +---------------+
| membership_id | | payment_id| | prediction  | | notification  |
| student_id FK | | studentFK | | student FK  | | student FK    |
| start_date    | | amount    | | score       | | message       |
| end_date      | | status    | | risk        | | status        |
+---------------+ +-----------+ +-------------+ +---------------+
```

---

# 5. Benefits

The ER design:

* Reduces data duplication
* Improves consistency
* Makes querying easier
* Supports future expansion

---

# End of ER Diagram
