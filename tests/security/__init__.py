"""W6.A6 — security floor tests.

A non-negotiable baseline for an institutional-AI product handling
real conversations. Six categories — one file each:

* ``test_xss_sanitization.py``           — chat content with script /
                                            javascript: / SVG / image
                                            payloads renders as text
* ``test_sql_injection_filter_params.py``— /trace-style filter params
                                            with SQL-shaped values
                                            rejected at the parameter
                                            layer, never reach the DB
* ``test_path_traversal_blocked.py``      — UUID-shaped route params
                                            with ``..`` / encoded
                                            traversal payloads return
                                            400
* ``test_mcp_bearer_token_forgery.py``    — every plausible token-
                                            forgery pattern (mismatched
                                            HMAC / expired / signed
                                            with wrong key / truncated /
                                            padded / empty / revoked)
                                            denied; legitimate-token
                                            rate counter NOT bumped by
                                            forgery attempts
* ``test_oauth_state_csrf.py``            — Slack/Discord/Teams
                                            callback rejects mismatched,
                                            missing, replayed, and
                                            cross-tenant OAuth state
* ``test_csrf_double_submit.py``          — dashboard write actions
                                            require either the OAuth-
                                            state cookie pattern OR a
                                            current-Person session;
                                            the four canonical CSRF
                                            failure modes covered

Each test asserts at the API/parameter-validation layer (status
code + named error). Tests don't depend on the renderer's runtime
behaviour; the assertions are about the wire contract.
"""
