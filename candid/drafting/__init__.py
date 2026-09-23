"""Context-aware email drafting.

Local-first, template-based drafting helpers. Every module in this package
builds *drafts only* -- nothing here may send email, open sockets, or make
network calls. Drafts are written to files/stdout for the user to review,
copy, and send themselves.
"""
