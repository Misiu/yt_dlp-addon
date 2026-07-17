# Security policy

## Supported versions

Security fixes are provided for the latest released version. Update the App before reporting an issue already fixed in a newer image.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Misiu/yt_dlp-app/security/advisories/new). Do not open a public issue for SSRF, path traversal, command injection, authentication/Ingress bypass, malicious media parsing, or container escape concerns.

Include the App version, architecture, Home Assistant version, reproduction steps, impact, and sanitized logs. Remove source URLs, usernames, media titles, tokens, IP addresses, cookies, and file contents. You should receive an acknowledgement within seven days. No bounty is promised.

## Operational guidance

Keep direct port 8099 disabled unless a trusted-LAN client requires it. Never expose that port to the internet. Use current App releases, protection mode, and the included AppArmor profile. The project will never request YouTube credentials by issue, log, or frontend.
