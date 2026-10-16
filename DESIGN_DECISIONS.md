# Design Decisions

These decisions apply to the current interview assessment implementation.

## Public signup

`POST /accounts/auth/signup` is public and accepts either a member or staff role. Omitting the role creates a member account.

Allowing anyone to create a staff account is intentional for testing and assessment review. It lets reviewers exercise both roles without database access or an existing administrator. Passwords are validated and hashed using Django's authentication utilities.

For a production application, public signup would assign the member role server-side, and staff accounts would be created through a trusted administrative process.

## JWT authentication

Protected endpoints require JWT authentication by default. Login issues access and refresh tokens. Refresh tokens rotate, and used refresh tokens are blacklisted after rotation.

Staff permissions use the application's `role` field, separately from Django's `is_staff` flag. Staff are not tied to any studio for now: a staff account can perform staff actions across all studios.
