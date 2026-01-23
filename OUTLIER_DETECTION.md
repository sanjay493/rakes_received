# Outlier Detection Feature

## Overview
The application now automatically detects and displays transit time outliers for every analysis selection. Outliers are records with transit times that are significantly different from the normal range.

## Detection Method: IQR (Interquartile Range)

### Formula
```
Q1 = 25th percentile of transit times
Q3 = 75th percentile of transit times
IQR = Q3 - Q1

Lower Bound = Q1 - 1.5 × IQR
Upper Bound = Q3 + 1.5 × IQR

Outliers = Records where:
  transit_time < Lower Bound OR transit_time > Upper Bound
```

### Why IQR Method?
- **Robust**: Not affected by extreme values in the data
- **Industry Standard**: Widely used in statistical analysis
- **Easy to Interpret**: Clear boundaries for normal vs abnormal
- **Visual**: Same method used in box plots

## What You'll See

### 1. Outliers Table
Located below the graph, the table shows:
- **Received Time**: When the rake was received (DD-MM-YYYY HH:MM)
- **Source Station**: Origin of the rake
- **Destination**: Where it arrived
- **Commodity**: Type of material transported
- **Rake Type**: Classification of the rake
- **Transit Time (Hrs)**: The outlier value highlighted in red

### 2. Table Features
- **Sorted**: Outliers sorted by transit time (highest first)
- **Numbered**: Each row has a sequential number
- **Highlighted**: Alternating row colors for readability
- **Color-Coded**: Transit times in red to emphasize outliers

### 3. Statistics Box
Shows:
- Total records analyzed
- Number of outliers detected
- Percentage of outliers
- Guidance message

## Use Cases

### 1. Identify Delays
Find rakes that took unusually long to arrive:
```
Example: If normal transit is 50-60 hours, 
outliers might be 80+ hours (upper outliers)
```

### 2. Data Quality Issues
Detect potentially incorrect entries:
```
Example: Transit time of 2 hours when normal is 50+ hours
(lower outliers - possibly data entry errors)
```

### 3. Performance Analysis
- Compare outliers across different sources
- Identify routes with frequent delays
- Track if outliers are increasing over time

### 4. Root Cause Investigation
Each outlier record provides complete information for:
- Tracking the specific rake
- Contacting source station
- Investigating commodity-specific issues
- Checking rake type patterns

## Interpretation Guide

### Upper Outliers (High Transit Time)
**Possible Causes:**
- Route congestion or delays
- Maintenance issues
- Weather conditions
- Operational inefficiencies
- Documentation delays

**Action:**
- Investigate specific routes
- Check with source stations
- Review operational logs

### Lower Outliers (Low Transit Time)
**Possible Causes:**
- Data entry errors
- Incorrect timestamp recording
- Express/priority shipments
- Direct routing

**Action:**
- Verify data accuracy
- Check if legitimate express delivery
- Review recording procedures

## Example Scenarios

### Scenario 1: High Outlier Count
```
Analysis: Last 30 Days - BSP
Outliers: 45 out of 200 records (22.5%)

Action Required:
- Investigate common patterns
- Check if specific sources have issues
- Review if commodity type affects delays
```

### Scenario 2: Specific Commodity Issues
```
Filter: BSP → Source: All → Commodity: IORE
Outliers: 15 out of 80 records (18.75%)

Insight: IORE shipments have higher delay rates
Action: Investigate IORE handling processes
```

### Scenario 3: Source-Specific Problem
```
Filter: BSP → Source: RDCR → All Commodities
Outliers: 10 out of 25 records (40%)

Insight: RDCR source has significant delays
Action: Contact RDCR for operational review
```

## Dynamic Filtering

Outliers update based on your selections:
- **Change Destination**: See outliers for that unit
- **Select Source**: See outliers from specific source
- **Filter Commodity**: See commodity-specific outliers
- **Choose Rake Type**: See rake type specific issues
- **Change Period**: See outliers in different timeframes

## Statistical Significance

### Understanding Percentages
- **<5%**: Normal distribution, few exceptional cases
- **5-10%**: Moderate variability, worth monitoring
- **10-20%**: High variability, investigation recommended
- **>20%**: Systemic issues likely present

### When to Act
- **Immediate**: >20% outliers or critical commodity
- **Soon**: 10-20% outliers showing trends
- **Monitor**: 5-10% outliers, track over time
- **Normal**: <5% outliers, expected variation

## Best Practices

### 1. Regular Review
- Check outliers weekly for high-volume routes
- Monthly review for all routes
- Compare trends over time

### 2. Documentation
- Record reasons for outliers when identified
- Track if patterns emerge
- Document corrective actions

### 3. Cross-Reference
- Use with other analysis periods
- Compare across sources
- Check commodity-specific patterns

### 4. Data Validation
- Verify lower outliers aren't data errors
- Confirm upper outliers with operational teams
- Update source data if corrections needed

## Technical Details

### Calculation
```python
# Calculate quartiles
Q1 = df['transit_time_hrs'].quantile(0.25)
Q3 = df['transit_time_hrs'].quantile(0.75)
IQR = Q3 - Q1

# Define boundaries
lower_bound = Q1 - 1.5 * IQR
upper_bound = Q3 + 1.5 * IQR

# Identify outliers
outliers = df[(df['transit_time_hrs'] < lower_bound) | 
              (df['transit_time_hrs'] > upper_bound)]
```

### Display Logic
- Sorted by transit time (descending)
- Formatted timestamps for readability
- Limited to selected filters
- Real-time calculation on each analysis

## Export Capability

Outliers can be exported via:
1. **CSV Export**: Use "Download CSV" button to get all data
2. **Copy Table**: Select and copy from browser
3. **Screenshot**: Capture for reports

## Future Enhancements

Potential improvements:
- Export outliers separately
- Trend analysis over time
- Alert thresholds
- Automatic notifications
- Outlier prediction
- Pattern recognition

---

**Remember**: Outliers aren't always bad - they're signals that something is different. Understanding why they occur is key to improving operations!
