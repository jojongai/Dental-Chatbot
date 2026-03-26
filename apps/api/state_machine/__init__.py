"""
Deterministic workflow state machine.

The state machine owns all slot-filling logic; it is completely independent of
any LLM. It inspects each user message with regex/keyword extractors, updates
the WorkflowState, and signals when the backend has enough information to call
a deterministic tool (lookup_patient, book_appointment, etc.).

Usage (in the router)::

    from state_machine.machine import WorkflowStateMachine
    from schemas.chat import WorkflowState

    result = WorkflowStateMachine(state).process(message)
    if result.ready_to_call:
        # call result.tool_name with result.tool_input_data
    return ChatResponse(reply=result.reply, state=result.state, actions=result.actions)
"""
