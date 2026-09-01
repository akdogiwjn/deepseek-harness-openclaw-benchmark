# W4: malformed tool-call recovery probe

This workspace is intentionally empty. The model endpoint is a deterministic
local mock. The first model response contains a malformed tool call; if the
runtime requests the model again, the second response is a normal completion.
