# How contact details are protected

We store a lead's phone number or email so counsellors can reach them. That
value is not written in the clear.

**Encryption.** `contact_encrypted` is a Fernet token (AES-128-CBC with HMAC).
The key lives only in `CIE_ENCRYPTION_KEY`. The process will not start if that
variable is missing, so a misconfigured deploy cannot persist plaintext by
accident.

**Lookup without decrypting.** `contact_hash` is HMAC-SHA256 of the already
normalised contact value, keyed by `CIE_CONTACT_HASH_KEY`. Two different keys
mean a leaked database cannot be searched with the encryption key alone, and
staff tools can still find a repeat enquiry without decoding the token.

**What we do not put in logs or audit.** Audit events refuse keys named `phone`,
`email`, `contact`, `contact_value`, or `name`. Application logs run through a
filter that replaces Indian phone numbers and email addresses, including values
nested inside dictionaries.
