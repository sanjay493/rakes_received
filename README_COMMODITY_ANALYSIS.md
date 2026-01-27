# Transit Time Analytics - Commodity Analysis Dashboard

## 🎯 Overview

A comprehensive commodity-wise analytics dashboard has been added to your Transit Time Analytics System. This new feature provides detailed insights into transit performance across all source stations, grouped by commodity and destination plant.

## ✨ New Features

### 1. **Commodity Analysis Dashboard** (`/commodity_analysis`)

A comprehensive tabular view that displays:

#### **Data Columns:**

**Recent Performance Metrics:**
- **Last 4 Months**: Average transit time and rake count
- **Last 8 Weeks**: Average transit time and rake count  
- **Last 4 Days**: Average transit time and rake count

**Best Performance Benchmarks:**
- **Best Monthly Avg**: Lowest average transit time from any single month in the last 12 months
- **Best Fortnightly Avg**: Lowest average transit time from any fortnight in the last 6 months
- **Best Weekly Avg**: Lowest average transit time from any week in the last 3 months
- **Rake Counts**: Hover over count values in "Best" columns to see sample sizes (number of rakes in that best-performing period)

**Outlier Analysis:**
- Link to view detailed outlier data for each source station from the last 30 days

#### **Features:**
- ✅ Grouped by commodity and destination plant
- ✅ Filterable by commodity and destination
- ✅ Color-coded columns for easy visual scanning
- ✅ Tooltip support on "Best" columns showing rake counts
- ✅ Responsive design with horizontal scrolling for wide tables
- ✅ Performance benchmarks to identify improvement opportunities

### 2. **Source Station Outliers Page** (`/source_outliers/<station_name>`)

Detailed outlier analysis for each source station:

#### **Features:**
- ✅ Lists all outlier rakes from the last 30 days
- ✅ Statistical summary (total rakes, outlier count, percentage)
- ✅ Performance assessment with color-coded alerts:
  - 🚨 **HIGH ALERT** (>20% outliers): Immediate action required
  - ⚠️ **MODERATE CONCERN** (10-20% outliers): Review patterns
  - 👀 **WORTH MONITORING** (5-10% outliers): Keep watching
  - ✅ **NORMAL OPERATION** (<5% outliers): Good consistency
- ✅ Complete outlier records table with all details
- ✅ CSV export functionality for further analysis
- ✅ Inherits commodity and destination filters from main dashboard
- ✅ Back navigation to commodity analysis dashboard

### 3. **Updated Navigation**

The main navigation bar now includes a "Commodity Analysis" link for easy access to the new dashboard.

## 📊 How to Use

### Accessing the Commodity Analysis Dashboard

1. Click **"Commodity Analysis"** in the top navigation bar
2. Optionally, select filters for specific commodity or destination
3. Review the comprehensive table showing all source stations grouped by commodity/destination
4. Compare recent performance against best benchmarks
5. Click **"View ⚠️"** in the Outliers column to see detailed outlier data

### Understanding the Data

**Recent Performance Columns (Left side):**
- Shows current operational performance over different time periods
- Helps identify short-term trends and patterns
- Use to monitor ongoing operations

**Best Performance Columns (Middle):**
- Represents peak performance benchmarks achieved in the past
- These are your targets for improvement
- Shows what's achievable based on historical data
- Hover over counts to see sample sizes

**Outliers Column (Right side):**
- Links to detailed analysis of abnormal transit times
- Uses IQR (Interquartile Range) statistical method
- Helps identify specific problematic rakes requiring investigation

### Interpreting the Results

**Good Performance Indicators:**
- Recent averages close to or better than best benchmarks
- Low outlier percentages (<5%)
- Consistent performance across time periods

**Areas Needing Attention:**
- Recent averages significantly higher than best benchmarks
- High outlier percentages (>10%)
- Large variations between different time periods

## 🔧 Technical Details

### Calculation Methods

**Averages:**
- All transit time averages are calculated in hours with 2 decimal precision
- Rake counts show the number of rakes received in each period

**Best Performance:**
- Monthly: Scans last 12 months, finds the single month with lowest average
- Fortnightly: Scans last 6 months, finds the best 2-week period
- Weekly: Scans last 3 months, finds the best single week
- Requires at least 1 rake in the period to be considered

**Outlier Detection:**
- Method: Interquartile Range (IQR)
- Lower bound: Q1 - 1.5 × IQR
- Upper bound: Q3 + 1.5 × IQR
- Any transit time outside these bounds is flagged as an outlier

### Data Grouping

Data is grouped hierarchically:
1. **Commodity** (e.g., IRON ORE, COAL, etc.)
2. **Destination Plant** (e.g., BSL, BSP, DSP, ISP, RSP)
3. **Source Station** (e.g., Bolani, Kalta, Kiriburu, etc.)

## 📁 File Structure

```
/mnt/user-data/outputs/
├── app.py                              # Updated Flask application with new routes
└── templates/
    ├── base.html                       # Updated base template with new nav link
    ├── dashboard.html                  # Existing dashboard (unchanged)
    ├── commodity_analysis.html         # NEW: Commodity analysis dashboard
    └── source_outliers.html           # NEW: Source station outlier details
```

## 🚀 Installation & Setup

### Prerequisites
- Existing Transit Time Analytics System must be running
- Flask application with SQLite database
- All dependencies from original system

### Installation Steps

1. **Backup your existing files:**
   ```bash
   cp app.py app.py.backup
   cp -r templates templates.backup
   ```

2. **Replace/Update files:**
   ```bash
   # Copy the updated app.py
   cp /mnt/user-data/outputs/app.py app.py
   
   # Copy the template files
   cp /mnt/user-data/outputs/templates/base.html templates/
   cp /mnt/user-data/outputs/templates/commodity_analysis.html templates/
   cp /mnt/user-data/outputs/templates/source_outliers.html templates/
   ```

3. **Restart the Flask application:**
   ```bash
   python app.py
   ```

4. **Access the new dashboard:**
   - Navigate to `http://localhost:5000/commodity_analysis`
   - Or click "Commodity Analysis" in the navigation bar

## 🎨 Dashboard Features

### Visual Design
- **Color-coded columns** for different time periods
- **Gradient headers** for visual hierarchy
- **Hover effects** on rows for better interactivity
- **Sticky headers** for easy reference while scrolling
- **Responsive layout** that works on different screen sizes

### Interactive Elements
- **Filter dropdowns** with auto-submit on change
- **Tooltips** on hover for additional information
- **Navigation links** that preserve filter context
- **Export functionality** for outlier data

### Data Visualization
- **Performance indicators** with color coding
- **Statistical summaries** for quick insights
- **Comparison metrics** between recent and best performance
- **Alert levels** based on outlier percentages

## 💡 Use Cases

### 1. Performance Monitoring
Track how current transit times compare to historical best performance for each route.

### 2. Identifying Improvement Opportunities
Find routes where recent performance is below historical benchmarks, indicating potential for improvement.

### 3. Outlier Investigation
Quickly identify and investigate rakes with abnormal transit times.

### 4. Route Comparison
Compare performance across different source stations for the same commodity-destination pair.

### 5. Trend Analysis
Monitor performance changes over different time periods (4 months, 8 weeks, 4 days).

## 📈 Sample Insights

**Example Analysis:**

If you see:
- **Last 4 Months Avg**: 45.5 hrs
- **Best Monthly Avg**: 38.2 hrs
- **Outlier %**: 15%

**Interpretation:**
- Current performance is ~7 hours slower than historical best
- Moderate outlier percentage suggests inconsistency
- Investigation needed to understand why performance has degraded
- Target should be to return to ~38 hours average

## 🔍 Troubleshooting

### No Data Showing
- **Check filters**: Remove filters to see if data exists
- **Verify data upload**: Ensure rake data has been uploaded
- **Check date ranges**: Confirm you have data in the relevant time periods

### Outlier Link Not Working
- **Verify route**: Ensure the `/source_outliers/<station>` route is accessible
- **Check station name**: Station names with spaces or special characters may need URL encoding

### Performance Issues
- **Large datasets**: If tables are slow, consider adding pagination
- **Filter usage**: Use filters to reduce the amount of data displayed
- **Browser**: Ensure using a modern browser with good performance

## 📞 Support

For questions or issues with the new dashboard:
1. Check this README for guidance
2. Review the inline comments in the code
3. Check browser console for JavaScript errors
4. Verify Flask application logs for server-side errors

## 🔄 Future Enhancements

Potential improvements to consider:
- **Pagination** for large tables
- **Sorting** on column headers
- **Advanced filtering** (date ranges, multiple selections)
- **Graph visualizations** of trends
- **Automated alerts** for high outlier percentages
- **Comparative analysis** between different time periods
- **Export to Excel** with formatting
- **Customizable thresholds** for outlier detection

## 📝 Notes

- All times are in hours with 2 decimal precision
- Outlier detection uses IQR method (industry standard)
- "Best" values represent actual historical performance, not theoretical targets
- Rake counts in "Best" columns show sample sizes for context
- Data is filtered by valid destinations (BSL, BSP, DSP, ISP, RSP)
- Empty cells (—) indicate no data available for that period

## ✅ Testing Checklist

After installation, verify:
- [ ] Commodity Analysis link appears in navigation
- [ ] Dashboard loads without errors
- [ ] Filters work and update the display
- [ ] Tables display data correctly
- [ ] Hover tooltips show rake counts
- [ ] Outlier links navigate correctly
- [ ] Outlier page displays data
- [ ] Back button returns to filtered view
- [ ] CSV export works on outlier page
- [ ] All styling renders correctly

---

**Version**: 1.0.0  
**Last Updated**: January 27, 2026  
**Compatibility**: Flask-based Transit Time Analytics System
