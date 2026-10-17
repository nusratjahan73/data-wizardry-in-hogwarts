/* Drawing the charts. This file has one job: turning numbers into SVG.
 * I use no charting library. I chose to build this page without a framework
 * or a bundler, and the three charts it needs are a line chart, a grouped bar
 * chart and a simple bar chart. Hand drawn SVG keeps the page to five small
 * files that anyone can read end to end, and the page needs no network.
 * Everything here is pure: each function takes data and returns an SVG string.
 * Nothing in this file touches the document. That is the job of page.js.
 */

const CHART = (function () {
  "use strict";

  const PAD = { top: 18, right: 18, bottom: 34, left: 52 };

  function scaleLinear(domainMin, domainMax, rangeMin, rangeMax) {
    const span = domainMax - domainMin || 1;
    return function (value) {
      return rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
    };
  }

  function escapeText(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function niceCeiling(value) {
    if (value <= 0) return 1;
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    return Math.ceil(value / magnitude) * magnitude;
  }

  /* Drawing the horizontal gridlines and their y axis labels. */
  function gridlines(yScale, maxValue, width, formatter) {
    const steps = 4;
    let out = "";
    for (let i = 0; i <= steps; i += 1) {
      const value = (maxValue / steps) * i;
      const y = yScale(value);
      out +=
        '<line class="chart__grid" x1="' + PAD.left + '" y1="' + y +
        '" x2="' + (width - PAD.right) + '" y2="' + y + '"/>' +
        '<text class="chart__label" x="' + (PAD.left - 8) + '" y="' + (y + 4) +
        '" text-anchor="end">' + formatter(value) + "</text>";
    }
    return out;
  }

  function xLabels(categories, xScale, height) {
    return categories
      .map(function (label, i) {
        return (
          '<text class="chart__label" x="' + xScale(i) + '" y="' + (height - PAD.bottom + 18) +
          '" text-anchor="middle">' + escapeText(label) + "</text>"
        );
      })
      .join("");
  }

  /* Drawing a line chart with several series. I use it for the seasonality comparison. */
  function lineChart(options) {
    const width = options.width || 620;
    const height = options.height || 300;
    const categories = options.categories;
    const series = options.series;

    const allValues = series.reduce(function (acc, s) {
      return acc.concat(s.values);
    }, []);
    const maxValue = niceCeiling(Math.max.apply(null, allValues) * 1.05);

    const xScale = scaleLinear(0, categories.length - 1, PAD.left + 10, width - PAD.right - 10);
    const yScale = scaleLinear(0, maxValue, height - PAD.bottom, PAD.top);

    let svg =
      '<svg class="chart" viewBox="0 0 ' + width + " " + height +
      '" role="img" aria-label="' + escapeText(options.ariaLabel || "line chart") + '">';

    /* Shading a band to mark the gift buying window. */
    if (options.band) {
      const x1 = xScale(options.band.from);
      const x2 = xScale(options.band.to);
      svg +=
        '<rect class="chart__band" x="' + x1 + '" y="' + PAD.top +
        '" width="' + (x2 - x1) + '" height="' + (height - PAD.bottom - PAD.top) + '"/>';
      if (options.band.label) {
        svg +=
          '<text class="chart__marker-label" x="' + ((x1 + x2) / 2) + '" y="' + (PAD.top + 14) +
          '" text-anchor="middle">' + escapeText(options.band.label) + "</text>";
      }
    }

    svg += gridlines(yScale, maxValue, width, options.formatY || String);

    series.forEach(function (s) {
      const points = s.values
        .map(function (value, i) {
          return xScale(i) + "," + yScale(value);
        })
        .join(" ");
      svg += '<polyline class="chart__line ' + s.className + '" points="' + points + '"/>';

      if (s.dotClassName) {
        s.values.forEach(function (value, i) {
          svg +=
            '<circle class="' + s.dotClassName + '" cx="' + xScale(i) + '" cy="' +
            yScale(value) + '" r="3.2"/>';
        });
      }
    });

    svg += xLabels(categories, xScale, height);
    svg += "</svg>";
    return svg;
  }

  /* Drawing grouped bars with a baseline line on top. I use it for the demand profile. */
  function groupedBarChart(options) {
    const width = options.width || 620;
    const height = options.height || 300;
    const categories = options.categories;
    const groups = options.groups;

    const allValues = groups.reduce(function (acc, g) {
      return acc.concat(g.values);
    }, options.baseline ? options.baseline.values.slice() : []);
    const maxValue = niceCeiling(Math.max.apply(null, allValues) * 1.08);

    const plotWidth = width - PAD.left - PAD.right;
    const slot = plotWidth / categories.length;
    const barWidth = (slot * 0.72) / groups.length;

    const yScale = scaleLinear(0, maxValue, height - PAD.bottom, PAD.top);
    const centreOf = function (i) {
      return PAD.left + slot * i + slot / 2;
    };

    let svg =
      '<svg class="chart" viewBox="0 0 ' + width + " " + height +
      '" role="img" aria-label="' + escapeText(options.ariaLabel || "bar chart") + '">';

    svg += gridlines(yScale, maxValue, width, options.formatY || String);

    groups.forEach(function (group, groupIndex) {
      group.values.forEach(function (value, i) {
        const offset = (groupIndex - (groups.length - 1) / 2) * barWidth;
        const x = centreOf(i) + offset - barWidth / 2;
        const y = yScale(value);
        svg +=
          '<rect class="' + group.className + '" x="' + x + '" y="' + y +
          '" width="' + barWidth + '" height="' + (height - PAD.bottom - y) + '"/>';
      });
    });

    if (options.baseline) {
      const points = options.baseline.values
        .map(function (value, i) {
          return centreOf(i) + "," + yScale(value);
        })
        .join(" ");
      svg += '<polyline class="chart__line chart__line--all-retail" points="' + points + '"/>';
    }

    /* Drawing a vertical marker between two categories, for the premiere. */
    if (options.marker) {
      const x = PAD.left + slot * (options.marker.afterIndex + 1);
      svg +=
        '<line class="chart__marker" x1="' + x + '" y1="' + PAD.top +
        '" x2="' + x + '" y2="' + (height - PAD.bottom) + '"/>' +
        '<text class="chart__marker-label" x="' + (x + 5) + '" y="' + (PAD.top + 12) + '">' +
        escapeText(options.marker.label) + "</text>";
    }

    const xScale = function (i) {
      return centreOf(i);
    };
    svg += xLabels(categories, xScale, height);
    svg += "</svg>";
    return svg;
  }

  /* Drawing bars for one series, with value labels. I use it for the reserve trade off. */
  function barChart(options) {
    const width = options.width || 620;
    const height = options.height || 260;
    const categories = options.categories;
    const values = options.values;

    const minValue = Math.min.apply(null, values);
    const maxValue = niceCeiling(Math.max.apply(null, values) * 1.06);
    const floor = Math.max(0, minValue * 0.9);

    const plotWidth = width - PAD.left - PAD.right;
    const slot = plotWidth / categories.length;
    const barWidth = slot * 0.6;
    const yScale = scaleLinear(floor, maxValue, height - PAD.bottom, PAD.top);

    let svg =
      '<svg class="chart" viewBox="0 0 ' + width + " " + height +
      '" role="img" aria-label="' + escapeText(options.ariaLabel || "bar chart") + '">';

    svg += gridlines(yScale, maxValue, width, options.formatY || String);

    values.forEach(function (value, i) {
      const x = PAD.left + slot * i + (slot - barWidth) / 2;
      const y = yScale(value);
      const isBest = i === options.highlightIndex;
      svg +=
        '<rect class="' + (isBest ? "chart__bar--central" : "chart__bar--baseline") +
        '" x="' + x + '" y="' + y + '" width="' + barWidth +
        '" height="' + (height - PAD.bottom - y) + '"/>';
      if (isBest) {
        svg +=
          '<text class="chart__value-label" x="' + (x + barWidth / 2) + '" y="' + (y - 6) +
          '" text-anchor="middle">' + escapeText(options.formatY(value)) + "</text>";
      }
    });

    const xScale = function (i) {
      return PAD.left + slot * i + slot / 2;
    };
    svg += xLabels(categories, xScale, height);
    svg += "</svg>";
    return svg;
  }

  /* Giving each legend item a CSS class, never an inline style attribute.
   * I allow no inline styles on this page, and I have a real reason for it. A
   * colour written here would be a second place where the palette lives, and
   * it would drift from base.css the first time I changed the palette. */
  function legend(items) {
    const parts = items.map(function (item) {
      return (
        '<span class="legend__item"><span class="legend__swatch ' +
        escapeText(item.swatchClass) + '"></span>' + escapeText(item.label) + "</span>"
      );
    });
    return '<div class="legend">' + parts.join("") + "</div>";
  }

  return {
    lineChart: lineChart,
    groupedBarChart: groupedBarChart,
    barChart: barChart,
    legend: legend
  };
})();
