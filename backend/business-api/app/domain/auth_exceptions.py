class AuthError(Exception):
    """Structured application errors without request, token, password or SQL details."""
    code = "UNAUTHENTICATED"
    message = "Authentication required"

    def __init__(self):
        super().__init__(self.message)


class InvalidCredentials(AuthError):
    code = "INVALID_CREDENTIALS"
    message = "Invalid credentials"


class Unauthenticated(AuthError):
    pass


class InvalidToken(AuthError):
    code = "INVALID_TOKEN"
    message = "Invalid token"


class TokenExpired(InvalidToken):
    code = "TOKEN_EXPIRED"
    message = "Token expired"


class Forbidden(AuthError):
    code = "FORBIDDEN"
    message = "Insufficient permissions"


class UserNotFound(AuthError):
    # This internal distinction is masked as INVALID_TOKEN in HTTP responses.
    code = "USER_NOT_FOUND"
    message = "Authentication required"


class AuthConfigurationError(AuthError):
    code = "AUTH_CONFIGURATION_ERROR"
    message = "Authentication unavailable"


class EmailAlreadyRegistered(AuthError):
    code = "EMAIL_ALREADY_REGISTERED"
    message = "Email is already registered"


class InvalidCurrentPassword(AuthError):
    code = "INVALID_CURRENT_PASSWORD"
    message = "Current password is invalid"


class PasswordUnchanged(AuthError):
    code = "PASSWORD_UNCHANGED"
    message = "New password must differ from the current password"
