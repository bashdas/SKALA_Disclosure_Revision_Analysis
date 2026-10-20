from uuid import UUID


class AnalysisError(Exception):
    code = "ANALYSIS_ERROR"
    message = "Analysis request failed"
    status_code = 503

    def __init__(self):
        super().__init__(self.message)


class AnalysisAlreadyRunning(AnalysisError):
    code = "ANALYSIS_ALREADY_RUNNING"
    message = "An active analysis already exists"
    status_code = 409

    def __init__(self, existing_task_id: UUID):
        super().__init__()
        self.existing_task_id = existing_task_id


class RabbitMQPublishFailed(AnalysisError):
    code = "RABBITMQ_PUBLISH_FAILED"
    message = "Unable to enqueue analysis"


class RabbitMQUnavailable(AnalysisError):
    code = "RABBITMQ_UNAVAILABLE"
    message = "Analysis queue unavailable"


class AnalysisNotFound(AnalysisError):
    code = "ANALYSIS_NOT_FOUND"
    message = "Analysis not found"
    status_code = 404


class AnalysisCannotBeCancelled(AnalysisError):
    code = "ANALYSIS_CANNOT_BE_CANCELLED"
    message = "Analysis cannot be cancelled"
    status_code = 409


class AnalysisCancelForbidden(AnalysisError):
    code = "ANALYSIS_CANCEL_FORBIDDEN"
    message = "Only the requester may cancel this analysis"
    status_code = 403


class InvalidLastEventID(AnalysisError):
    code = "INVALID_LAST_EVENT_ID"
    message = "Last-Event-ID must be a nonnegative sequence integer"
    status_code = 400


class InvalidEventPayload(AnalysisError):
    code = "INVALID_EVENT_PAYLOAD"
    message = "Event payload must contain bounded progress summary fields only"
    status_code = 400


class InvalidStreamQuery(AnalysisError):
    code = "INVALID_STREAM_QUERY"
    message = "Only after_sequence is accepted; authentication requires Authorization header"
    status_code = 400
