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
