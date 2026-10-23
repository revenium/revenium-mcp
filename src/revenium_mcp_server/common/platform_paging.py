"""Paging limits the Revenium platform imposes on its Spring Pageable list routes."""

# The platform serves at most this many rows per page on a Spring Pageable list
# route (spring.data.web.pageable.max-page-size in the hypercurrent api module's
# application.properties); dev answered size=200 and size=1000 on both log
# endpoints with 100 rows (2026-10-17). A larger size is silently clamped.
# An endpoint that enforces its own limit (the isotope insights routes, the
# provider key search, the analytics endpoints) keeps its own bound, which this
# cap moving must not change.
PLATFORM_MAX_PAGE_SIZE = 100
