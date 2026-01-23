# Transit Analytics System - Enhanced Version

## Overview
This enhanced version of the Transit Analytics System includes three major improvements:

1. **Dual-Axis Chart**: Shows daily rake count (bars) alongside average transit time (line)
2. **Dynamic Filters**: Source, commodity, and rake type filters update dynamically based on selections
3. **Selection Labels**: Clear display of current filter selections

## Requirements Implemented

### ✅ Requirement 1: Dual-Axis Chart with Rake Count + Transit Time

**Implementation:**
- Modified `app.py` (lines 371-569) to use Plotly Graph Objects for dual-axis charts
- Left Y-axis: Average Transit Time (Hours) - shown as line chart with markers
- Right Y-axis: Rake Count - shown as bar chart
- Both metrics are calculated for each time period (daily, weekly, fortnightly, monthly)

**Visual Features:**
- Blue line with markers for transit time
- Gray bars for rake count
- Unified hover mode showing both metrics
- Clear color coding and legends

**Code Changes:**
```python
# Example for daily analysis
result = df.groupby("date", as_index=False).agg({
    'transit_time_hrs': 'mean',
    'sttn_from': 'count'  # Count of rakes
})

fig = go.Figure()

# Add bar for rake count
fig.add_trace(go.Bar(
    x=result['date'],
    y=result['rake_count'],
    name='Rake Count',
    yaxis='y2'
))

# Add line for transit time
fig.add_trace(go.Scatter(
    x=result['date'],
    y=result['avg_transit_time'],
    name='Avg Transit Time',
    mode='lines+markers',
    yaxis='y'
))
```

### ✅ Requirement 2: Dynamic Filter Population

**Implementation:**
- Added new API endpoint `/api/get_filters` (lines 215-268 in app.py)
- JavaScript event listeners in dashboard.html detect filter changes
- Real-time updates to available options based on current selections

**How It Works:**
1. When user changes any filter (source, commodity, or rake type)
2. JavaScript calls `/api/get_filters` with current selections
3. Backend queries database for valid combinations
4. Frontend updates other dropdowns with available options
5. Invalid combinations are automatically filtered out

**Filter Logic:**
- Source filter: Shows sources available for selected commodity + rake type
- Commodity filter: Shows commodities available for selected source + rake type
- Rake Type filter: Shows rake types available for selected source + commodity
- All filters respect the selected destination/unit

**Code Changes:**
```javascript
// Event listener example
document.getElementById('sourceSelect').addEventListener('change', function() {
    updateFilters('source');  // Updates commodity and rake type options
});

// API call to get filtered options
const response = await fetch('/api/get_filters', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        destination: destination,
        source: source,
        commodity: commodity,
        rake_type: rakeType
    })
});
```

### ✅ Requirement 3: Selection Labels Display

**Implementation:**
- Added prominent card in dashboard.html (lines 15-35)
- Shows current selections for: Destination, Source Station, Commodity, Rake Type
- Color-coded with gradient background for visibility
- Labels passed from backend with "All X" defaults for unselected filters

**Visual Design:**
- Purple gradient background card
- Grid layout with 4 sections
- White text on translucent backgrounds
- Updates automatically when filters change

**Code Changes:**
```python
# Backend passes labels
source_label = sttn_from if sttn_from else "All Sources"
commodity_label = commodity if commodity else "All Commodities"
rake_type_label = rake_type if rake_type else "All Rake Types"

return render_template(
    "dashboard.html",
    ...
    source_label=source_label,
    commodity_label=commodity_label,
    rake_type_label=rake_type_label,
    ...
)
```

## File Structure

```
rakes_received/
│
├── app.py                 # Enhanced Flask application
├── rake_data.db          # SQLite database (created on first upload)
├── uploads/              # Temporary CSV upload folder
│
└── templates/
    ├── base.html         # Base template with navigation
    ├── upload.html       # CSV upload page
    └── dashboard.html    # Main dashboard with all enhancements
```

## Installation & Setup

### Prerequisites
```bash
pip install flask pandas plotly sqlalchemy
```

### Database Setup
The database is automatically created on first run. Structure:
- Table: `rakes`
- Key fields: received_time, sttn_from, sttn_to, cmdt, rake_type, transit_time_hrs
- Unique constraint prevents duplicates

### Running the Application
```bash
python app.py
```

Access at: `http://localhost:5000`

## Usage Guide

### 1. Upload Data
1. Navigate to Upload page
2. Select CSV file with rake data
3. System automatically cleans and validates data
4. Destination codes are standardized (BSCS→BSL, BSPC→BSP, etc.)

### 2. View Dashboard
1. Click destination unit button (BSL, BSP, DSP, ISP, RSP)
2. Filters automatically populate for that destination
3. Select source, commodity, and/or rake type
4. Other filters update dynamically as you select
5. Choose analysis period
6. Click "Run Analysis" to generate chart

### 3. Interpret Charts
- **Bars (Right Y-axis)**: Number of rakes received per period
- **Line (Left Y-axis)**: Average transit time in hours
- Hover over any point to see both metrics
- Use zoom and pan tools for detailed analysis

### 4. Export Data
- Click "Download CSV" to export filtered analysis
- Includes both rake count and average transit time
- Data matches the displayed chart

## Technical Details

### Dynamic Filter Algorithm
1. Base query filters by destination
2. For each filter dropdown:
   - Apply OTHER selected filters
   - Query distinct values
   - Update dropdown options
3. If previously selected value becomes invalid, reset to "All"

### Chart Rendering
- Uses Plotly.js for interactive charts
- Responsive design adapts to screen size
- Full HTML export available via Plotly API

### Data Aggregation
- **Daily**: Exact date grouping
- **Weekly**: 7-day windows using pandas resample
- **Fortnightly**: 14-day windows
- **Monthly**: Calendar month boundaries

## Database Schema

```sql
CREATE TABLE rakes (
    id INTEGER PRIMARY KEY,
    sr_no VARCHAR,
    received_time DATETIME,
    dispatched_time DATETIME,
    transit_time VARCHAR,
    transit_time_hrs FLOAT,
    sttn_from VARCHAR,
    sttn_to VARCHAR,
    cmdt VARCHAR,
    rake_type VARCHAR,
    totl_unts INTEGER,
    UNIQUE(received_time, sttn_from, sttn_to, cmdt, rake_type, dispatched_time)
);
```

### Indexes
- received_time (for date range queries)
- sttn_from (for source filtering)
- sttn_to (for destination filtering)
- cmdt (for commodity filtering)
- rake_type (for rake type filtering)

## API Endpoints

### GET /
Redirects to dashboard

### GET/POST /upload
Upload and process CSV files

### GET/POST /dashboard
Main dashboard with filters and analysis
- GET: Display dashboard with optional unit parameter
- POST: Submit filters and generate analysis

### POST /api/get_filters
Get dynamically filtered options
- Input: JSON with destination, source, commodity, rake_type
- Output: JSON with arrays of valid options for each filter

### POST /export
Export filtered data as CSV

## Troubleshooting

### Filters Not Updating
- Check browser console for JavaScript errors
- Ensure /api/get_filters endpoint is accessible
- Verify database has data for selected destination

### Chart Not Displaying
- Check that data exists for selected filters and period
- Verify Plotly.js is loaded (check browser network tab)
- Look for errors in Flask console

### Upload Failing
- Ensure CSV has required columns
- Check date format: DD-MM-YYYY HH:MM
- Verify destination codes are valid

## Performance Considerations

- Dynamic filters query database in real-time
- Large datasets (>100k records) may cause slow filter updates
- Consider adding indexes for frequently filtered columns
- Chart rendering limited to displayed time period

## Future Enhancements

Potential improvements:
1. Add caching for filter options
2. Implement pagination for large datasets
3. Add more chart types (heatmaps, scatter plots)
4. Export charts as images
5. Add user authentication
6. Real-time data updates via WebSockets
7. Comparative analysis across destinations
8. Predictive analytics for transit times

## Support

For issues or questions:
1. Check Flask console for error messages
2. Verify database connectivity
3. Ensure all dependencies are installed
4. Check browser console for JavaScript errors

## Version History

### Version 2.0 (Enhanced)
- ✅ Dual-axis charts with rake count + transit time
- ✅ Dynamic filter population
- ✅ Selection labels display
- ✅ Improved UI/UX

### Version 1.0 (Original)
- Basic dashboard with line charts
- Static filters
- CSV upload functionality

---

**Created:** January 2026  
**Status:** Production Ready  
**License:** Internal Use
