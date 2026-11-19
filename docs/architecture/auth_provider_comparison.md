# D-01 — Authentication provider comparison (Supabase Auth, AWS Cognito, Auth0)

**Status:** recommendation for owner approval. **No provider has been integrated,
no account created and no paid service started.** Facts were checked against the
providers' official documentation and pricing pages on 19 November 2026 (sources
in §6). Where a page did not state a fact, it is marked *not verified*. Prices are
list prices in US dollars, before tax, and can change.

## 1. How Diski 9 will use the provider (same for all three)

The provider is used **only to prove who someone is**. Everything else stays in
the Diski 9 database:

1. The browser is redirected to the provider (authorization code flow with PKCE,
   OpenID Connect).
2. The Flask server behind Dash receives the code, exchanges it, and validates the
   ID token (signature from the provider's JWKS, issuer, audience, nonce, expiry).
3. Diski 9 finds or creates the user by `(provider, subject)` and starts **its own
   server-side session**: a random session ID in a `__Host-` cookie (HttpOnly,
   Secure, SameSite=Lax) pointing to a row in `app_sessions`.
4. Roles (D-34), entitlements, usernames, terms acceptance and privacy settings
   live in the Diski 9 database and are checked server-side on every write. They
   are **not** taken from token claims, so changing provider never changes
   permissions.
5. Diski 9 does not keep provider access or refresh tokens after sign-in (it never
   calls provider APIs on the user's behalf), which removes most token handling.
6. Logout revokes the Diski 9 session row, clears the cookie and calls the
   provider's logout endpoint. Account deletion (D-36) also calls the provider's
   admin delete API.

No passwords are stored or handled by Diski 9 under any option.

## 2. Comparison

| Criterion | Supabase Auth | AWS Cognito (user pools) | Auth0 |
|---|---|---|---|
| **Python / Flask / Dash integration** | Server-side PKCE via `supabase-py`, or a generic OIDC client against Supabase's OAuth 2.1 / OIDC server. No Dash-specific code needed | Generic OIDC client (for example Authlib) against the managed login domain; AWS SDK (`boto3`) for admin tasks | Official Flask quickstart using `auth0-server-python` (beta SDK); any OIDC client also works |
| **OpenID Connect** | Yes: OAuth 2.1 and OIDC server, authorization code with mandatory PKCE, ID tokens, UserInfo, JWKS, discovery at `https://<project>.supabase.co/auth/v1/.well-known/openid-configuration` | Yes: the user pool is an OIDC provider; managed login supplies authorize, token, userInfo, revoke and logout endpoints; PKCE supported | Yes: standard OIDC provider; RP-initiated logout supported |
| **Email verification and recovery** | Confirmation and password-reset flows built in; **custom SMTP required for production** (the default sender is limited to 2 emails an hour and to team addresses) | Built in; email through Amazon SES (the default sender is limited to 50 emails a day) | Built in; custom email templates need Essentials or higher |
| **Google and social sign-in** | Google, Apple, Facebook, Microsoft, Discord, GitHub and many others; custom OIDC providers | Google, Facebook, Apple, Amazon; any OIDC or SAML provider | Unlimited social connections on all plans |
| **Passwordless / MFA** | Magic links and email OTP; TOTP MFA on all plans (phone MFA is a $75 a month add-on) | Authenticator and SMS MFA on all plans; email OTP, passwordless and passkeys need Essentials | Passwordless and passkeys on all plans; MFA factors from Essentials |
| **Local development and testing** | **Best:** the Supabase CLI runs the full auth stack in Docker, with Mailpit to capture emails | No official local emulator (*none found in the documentation*); needs a cloud development pool | No local emulator; development tenants (Free plan: 1 tenant) |
| **Server-side sessions** | Diski 9 sessions (§1). Provider sessions: 1-hour access tokens by default; single-use refresh tokens; time-boxed and inactivity limits need Pro | Diski 9 sessions. Tokens: refresh 60 minutes to 10 years (default 30 days); rotation optional | Diski 9 sessions. Idle and maximum session lifetimes configurable; refresh-token rotation |
| **Logout and token handling** | Sign-out deletes the provider session; session ID claim in tokens | Logout endpoint, token revocation, global sign-out | OIDC RP-initiated logout; refresh-token revocation |
| **Roles and entitlements** | Kept in Diski 9 (optional custom access-token hook exists) | Kept in Diski 9 (groups and pre-token Lambda exist) | Kept in Diski 9 (RBAC exists but needs Essentials) |
| **User deletion and lifecycle** | Admin API `auth.admin.delete_user` in Python (soft or hard delete) | `AdminDeleteUser` API | Management API `DELETE /api/v2/users/{id}` |
| **Data portability / lock-in** | **Lowest:** open source and self-hostable; users live in PostgreSQL tables of your project | **Highest:** AWS-specific; password hashes are generally understood not to be exportable (*not verified in this review*), so migrating away usually means password resets | Moderate: proprietary; exports via the Management API |
| **Regions** | Europe (London, Ireland, Frankfurt, Paris, Zurich, Stockholm) and others; **no African region** | Includes **Africa (Cape Town, `af-south-1`)** and Europe | Region list *not verified* (the regions page could not be retrieved) |
| **Security and operations** | Low operational effort; custom SMTP to set up; newer OAuth server feature | Highest operational effort (AWS accounts, IAM, SES, Lambda triggers) but very mature | Lowest effort, most mature product; free tenants with no activity for 150 days are scheduled for deletion |

## 3. Indicative monthly costs (authentication only)

| Active users per month | Supabase | AWS Cognito (Essentials or Lite) | Auth0 |
|---|---|---|---|
| **100** | $0 on Free (development only); **$25** on Pro for production | **$0** (10,000 MAU free tier, permanent) | $0 on Free; $35 on Essentials (500 MAU minimum) |
| **1,000** | **$25** (Pro includes 100,000 MAU) | **$0** | $0 on Free; **$70** on Essentials |
| **10,000** | **$25** | **$0** | $0 on Free; **$700** on Essentials; $1,600 on Professional |

Notes:
* **Supabase Free** has no backups, pauses projects after a week of inactivity and
  limits active projects to two, so production would use **Pro ($25 a month)**.
  Pro includes 100,000 MAU (then $0.00325 each) and a Micro database instance, so
  the same $25 could also host the competition database if D-02 later chooses
  Supabase; that choice is not required.
* **Cognito:** 10,000 MAU are free for Lite and Essentials (Essentials then $0.015
  per MAU; at 20,000 MAU about $150 a month). SAML/OIDC-federated users have only
  50 free MAU; Google sign-in counts as social, not federated. Amazon SES email
  is billed separately.
* **Auth0 Free** covers 25,000 MAU but keeps logs for one day, has no custom email
  templates and no role management; Diski 9 does not need Auth0 roles, but custom
  branded emails would push it to Essentials.
* **All options:** a transactional email service for verification and recovery
  emails is a small extra cost (often free at low volume).

## 4. Assessment

* **Supabase Auth:** standard OIDC with PKCE, the best local development story
  (complete local stack with an email inbox, matching the Docker Compose
  approach), low and predictable cost, a Python admin API for deletion, and the
  lowest lock-in (open source, self-hostable, users stored in PostgreSQL).
  Weaknesses: no African region (this affects sign-in latency only; it was not
  measured for this review), custom SMTP is required, and its
  OIDC-server feature is newer than the other two products.
* **AWS Cognito:** the cheapest at these volumes and the only one with a Cape Town
  region, but the most operational complexity, no local emulator and the
  strongest lock-in. It becomes attractive only if Phase 10 hosting is on AWS.
* **Auth0:** the most polished and the quickest to integrate, but its paid tiers
  are expensive at 10,000 users ($700 a month on Essentials), the Python SDK in
  the official quickstart is a beta, and free tenants can be deleted after 150
  days without activity.

## 5. Recommendation

**Supabase Auth** (Free project for development, Pro for production), integrated
as described in §1:
* server-side authorization code flow with PKCE; ID-token validation; Diski 9's
  own server-side sessions;
* roles, entitlements and profiles kept in the Diski 9 database (no reliance on
  provider claims, no browser access to the database, no row-level security
  dependence);
* Google plus email (magic link or email and password handled by Supabase) at
  launch; other social providers optional;
* tests use a local OIDC test double, and the Supabase CLI stack for end-to-end
  sign-in tests;
* a custom SMTP sender before beta.

Using Supabase Auth does **not** commit the competition database to Supabase
hosting: the competition database stays plain PostgreSQL (Docker Compose locally),
and the production database host remains part of D-02 in Phase 10.

**Runner-up:** AWS Cognito, if the Phase 10 hosting decision selects AWS (Cape
Town region, no cost at these volumes).

## 6. Sources (official pages, read 19 November 2026)

* Supabase: supabase.com/pricing; docs/guides/auth; docs/guides/auth/sessions;
  docs/guides/auth/social-login/auth-google; docs/guides/auth/oauth-server and
  .../getting-started; docs/guides/auth/passwords; docs/guides/auth/auth-smtp;
  docs/guides/local-development and .../cli/testing-and-linting;
  docs/guides/platform/regions; docs/guides/platform/billing-on-supabase;
  docs/guides/platform/manage-your-usage/monthly-active-users;
  docs/reference/python/auth-admin-deleteuser.
* AWS: aws.amazon.com/cognito/pricing; Cognito developer guide pages on user
  pools, feature plans, managed login, tokens, refresh tokens, token revocation,
  pre-token generation, PKCE, quotas and user import; AWS General Reference,
  Amazon Cognito endpoints.
* Auth0: auth0.com/pricing; docs/quickstart/webapp/python;
  docs/manage-users/sessions and .../configure-session-lifetime;
  docs/authenticate/login/logout and .../log-users-out-of-auth0; docs/secure/tokens
  and .../refresh-tokens; docs/manage-users/access-control/rbac;
  docs/manage-users/user-accounts/delete-users;
  docs/api/management/v2/users/delete-users-by-id;
  docs/secure/data-privacy-and-compliance/data-processing.
