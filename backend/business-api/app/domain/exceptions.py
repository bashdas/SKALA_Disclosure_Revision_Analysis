from app.models.enums import AnalysisStage, AnalysisStatus, PerspectiveStatus


class InvalidAnalysisStateTransition(ValueError):
    code = "INVALID_ANALYSIS_STATE"

    def __init__(self, current_status: AnalysisStatus, target_status: AnalysisStatus):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Invalid analysis transition: {current_status} -> {target_status}")


class InvalidAnalysisStageTransition(ValueError):
    code = "INVALID_ANALYSIS_STAGE"

    def __init__(self, current_stage: AnalysisStage | None, target_stage: AnalysisStage, status: AnalysisStatus):
        self.current_stage = current_stage
        self.target_stage = target_stage
        self.status = status
        super().__init__(f"Invalid analysis stage transition: {current_stage} -> {target_stage} (status={status})")


class InvalidPerspectiveStateTransition(ValueError):
    code = "INVALID_PERSPECTIVE_STATE"

    def __init__(self, current_status: PerspectiveStatus, target_status: PerspectiveStatus):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Invalid perspective transition: {current_status} -> {target_status}")
