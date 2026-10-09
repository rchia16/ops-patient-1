"""Optional host-side before-display gate. Wire every patient output through this.
Not automatically installed inside ChatGPT's renderer by an MCP connection.
"""
from validation import CaseError

class ResponseGateway:
    def __init__(self, backend, emit):
        self.backend, self.emit = backend, emit

    def show(self, session_id, proposed_response, evidence_refs):
        verdict=self.backend.validate_response(session_id,proposed_response,evidence_refs)
        if not verdict['may_show']:
            self.emit('This response cannot be verified against the authoritative case.')
            return verdict
        self.backend.record_interaction(session_id,{'actor':'assistant','text':proposed_response,'evidence_refs':evidence_refs})
        self.emit(proposed_response)
        return verdict
