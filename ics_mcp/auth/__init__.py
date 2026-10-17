"""OAuth and JWT verification. stdio: PKCE loopback flow, tokens in the OS
keyring. HTTP: the client does OAuth against ICS and this server checks the
Bearer JWT locally via JWKS."""
