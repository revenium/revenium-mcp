"""
API key costs response formatter.

Dedicated formatter for API key cost analysis responses,
following single responsibility principle.
"""

from typing import Any, Dict, List

from .base_formatter import AnalyticsResponseFormatter


class ApiKeyCostsFormatter(AnalyticsResponseFormatter):
    """Format API key costs analytics responses."""

    def format(self, data: List[Dict[str, Any]], params: Dict[str, Any]) -> str:
        """Format API key costs data for response.

        Args:
            data: API key cost data from API
            params: Formatting parameters (period, aggregation)

        Returns:
            Formatted API key costs response string
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        if not data:
            return self.utilities.format_no_data_response(
                "API key costs", period, f"aggregation: {aggregation}"
            )

        # BACK-1270 / item #8: distinct upstream API keys can mask to the same
        # label (e.g. two ANONYMOUS rows -> ANON****MOUS), producing rows the
        # caller cannot disambiguate. Collapse colliding masked labels into a
        # single row before formatting.
        aggregated = self._aggregate_by_masked_label(data)

        return self._format_api_key_costs_content(
            aggregated, {"period": period, "aggregation": aggregation}
        )

    def _aggregate_by_masked_label(
        self, rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge rows whose masked label collides; sum cost + percentage.

        BACK-1270 / item #8: two distinct upstream api keys can produce the
        same masked label (e.g. both ``ANONYMOUS`` -> ``ANON****MOUS``), and
        indistinguishable rows confuse callers. Group by what
        :meth:`_mask_api_key_name` produces; one emitted row per masked label.
        Groups with more than one source row get a ``note`` field documenting
        the source count so callers know the row is an aggregation.

        Debug rows (``api_key == "DEBUG_INFO"``) and rows with no ``api_key``
        are passed through unchanged so existing debug / unknown-key handling
        is preserved.

        Args:
            rows: Raw API key cost rows from upstream.

        Returns:
            Aggregated row list, preserving first-seen order, with summed
            ``cost`` and ``percentage`` and an optional ``note`` field on
            collapsed groups.
        """
        groups: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        sources_per_group: Dict[str, int] = {}
        passthrough: List[Dict[str, Any]] = []

        for row in rows:
            api_key_name = row.get("api_key")
            # Pass-through: debug rows and rows missing the api_key field
            # bypass aggregation entirely (preserves existing behavior).
            if api_key_name is None or api_key_name == "DEBUG_INFO":
                passthrough.append(row)
                continue

            masked = self._mask_api_key_name(api_key_name)
            if masked not in groups:
                # Seed with a copy of the row, then overwrite the cost /
                # percentage fields so the running sum starts at zero.
                seed = dict(row)
                seed["cost"] = 0.0
                if "percentage" in row:
                    seed["percentage"] = 0.0
                groups[masked] = seed
                sources_per_group[masked] = 0
                order.append(masked)

            sources_per_group[masked] += 1
            groups[masked]["cost"] = float(groups[masked].get("cost", 0.0)) + float(
                row.get("cost", 0.0) or 0.0
            )
            if "percentage" in row:
                current = float(groups[masked].get("percentage", 0.0) or 0.0)
                groups[masked]["percentage"] = current + float(row.get("percentage", 0.0) or 0.0)

        out: List[Dict[str, Any]] = []
        for masked in order:
            row = groups[masked]
            count = sources_per_group[masked]
            if count > 1:
                row["note"] = f"aggregated {count} sources with the same masked label"
            out.append(row)

        # Append any pass-through rows after aggregated rows so debug / unknown
        # entries continue to render in their existing position-independent way.
        out.extend(passthrough)
        return out

    def _format_api_key_costs_content(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format the main API key costs content with proper decomposition.

        Args:
            data: API key cost data
            params: Parameters containing period and aggregation

        Returns:
            Formatted response content
        """
        header = self._format_api_key_costs_header(data, params)
        table_content = self._format_api_key_costs_table(data)
        footer = self._format_api_key_costs_footer(params)

        return f"{header}\n\n{table_content}\n{footer}"

    def _format_api_key_costs_header(
        self, data: List[Dict[str, Any]], params: Dict[str, Any]
    ) -> str:
        """Format header section for API key costs display.

        Args:
            data: API key cost data for counting keys
            params: Parameters containing period and aggregation

        Returns:
            Formatted header section
        """
        timestamp = self.utilities.get_timestamp()
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")

        return f"""# **API Key Cost Analysis**

## **Analysis Summary**
- **Time Period**: {period}
- **Aggregation**: {aggregation}
- **API Keys Found**: {len(data)}
- **Analysis Date**: {timestamp}

## **API Key Cost Ranking**
"""

    def _format_api_key_costs_table(self, data: List[Dict[str, Any]]) -> str:
        """Format table section for API key costs data.

        Args:
            data: API key cost data to format

        Returns:
            Formatted table section
        """
        table_content = ""

        for i, api_key in enumerate(data, 1):
            api_key_entry = self._format_single_api_key_entry(api_key, i)
            table_content += api_key_entry

        return table_content

    def _format_single_api_key_entry(self, api_key: Dict[str, Any], index: int) -> str:
        """Format a single API key entry for the table.

        Args:
            api_key: Single API key data
            index: API key index for numbering

        Returns:
            Formatted API key entry
        """
        api_key_name = api_key.get("api_key", "Unknown API Key")

        # Handle debug information - only show in debug mode
        if api_key_name == "DEBUG_INFO" and "debug" in api_key:
            return self._format_debug_entry(api_key)

        return self._format_regular_api_key_entry(api_key, index)

    def _format_debug_entry(self, api_key: Dict[str, Any]) -> str:
        """Format debug information entry.

        Args:
            api_key: API key data containing debug info

        Returns:
            Formatted debug entry or empty string if in production mode
        """
        if not self.production_mode:
            return f"## **DEBUG INFORMATION**\n\n**Debug Details**: {api_key['debug']}\n\n"
        return ""

    def _format_regular_api_key_entry(self, api_key: Dict[str, Any], index: int) -> str:
        """Format a regular API key entry with cost and optional details.

        Args:
            api_key: API key data
            index: API key index for numbering

        Returns:
            Formatted API key entry
        """
        api_key_name = api_key.get("api_key", "Unknown API Key")
        cost = api_key.get("cost", 0)
        cost_formatted = self.utilities.format_currency(cost)

        # Mask sensitive API key names for security
        masked_key_name = self._mask_api_key_name(api_key_name)

        entry = f"**{index}. {masked_key_name}**\n   - Cost: {cost_formatted}\n"

        if "percentage" in api_key:
            entry += f"   - Share: {api_key['percentage']:.1f}%\n"

        # BACK-1270 / item #8: surface aggregation note when multiple upstream
        # rows collapsed into this one (e.g. two ANONYMOUS sources merged).
        note = api_key.get("note")
        if note:
            entry += f"   - Note: {note}\n"

        # Add debug information if available - only in debug mode
        if not self.production_mode and "debug_metrics_count" in api_key:
            debug_structure = api_key.get("debug_metrics_structure", "N/A")
            entry += f"   - Debug: {api_key['debug_metrics_count']} metrics, structure: {debug_structure}\n"

        return entry + "\n"

    def _mask_api_key_name(self, api_key_name: str) -> str:
        """Mask API key names for security purposes.

        Args:
            api_key_name: Original API key name

        Returns:
            Masked API key name
        """
        if not api_key_name or api_key_name == "Unknown API Key":
            return api_key_name

        # Show first 4 and last 4 characters, mask the middle
        if len(api_key_name) <= 8:
            return api_key_name[:2] + "****" + api_key_name[-2:]
        else:
            return api_key_name[:4] + "****" + api_key_name[-4:]

    def _format_api_key_costs_footer(self, params: Dict[str, Any]) -> str:
        """Format footer section with insights and totals.

        Args:
            params: Parameters containing period and aggregation

        Returns:
            Formatted footer section
        """
        period = params.get("period", "Unknown")
        aggregation = params.get("aggregation", "Unknown")
        return self.utilities.add_insights_footer(
            "API key costs", period, f"{aggregation} aggregation"
        )
