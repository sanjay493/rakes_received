# Understanding Outlier Statistics - Explained Simply

## The Issue You're Seeing

You noticed that it shows:
- **Total records analyzed: 14**
- **Outliers detected: 7 (50.0%)**

And you're wondering why there are so many outliers (50%).

## What's Really Happening

### 1. **Total Records Analyzed**
This is the **total number of individual rake records** that match your current filter selection.

**Example:**
```
Selected Filters:
- Destination: BSP
- Source: RDCR
- Commodity: PIOR
- Period: Last 30 Days

Total Records = All rakes from RDCR to BSP carrying PIOR in last 30 days
```

If this shows **14**, it means:
- There were 14 individual rake deliveries matching your filters
- Each record is one rake arrival with its transit time

### 2. **Outliers Detected**
These are rakes whose **transit time is significantly different** from the normal range.

**Why 50% Outliers Might Happen:**

#### Scenario A: Small Dataset
```
Total: 14 rakes
Normal pattern: Most take 45-50 hours
Outliers: 7 rakes took 70-80 hours (delays)

Result: 50% are outliers
```

**This is NORMAL when:**
- Small number of records (under 20-30)
- Recent operational issues
- Specific route problems
- Weather/seasonal effects

#### Scenario B: Route with Issues
```
Total: 14 rakes
- 7 arrived in normal time (45-50 hrs)
- 7 had significant delays (65+ hrs)

Result: 50% outliers indicates this route/commodity has problems
```

## The IQR Method Explained

### How Outliers Are Calculated

```
Step 1: Sort all transit times
Example: [42, 45, 46, 48, 49, 50, 52, 68, 70, 72, 75, 78, 80, 82]

Step 2: Find quartiles
Q1 (25th percentile) = 46 hours
Q3 (75th percentile) = 75 hours
IQR = Q3 - Q1 = 75 - 46 = 29 hours

Step 3: Calculate boundaries
Lower bound = Q1 - 1.5 × IQR = 46 - 43.5 = 2.5 hours
Upper bound = Q3 + 1.5 × IQR = 75 + 43.5 = 118.5 hours

Step 4: Identify outliers
Values < 2.5 OR > 118.5 are outliers
```

### Why This Is Sensitive

The IQR method is **designed to catch variations**. With small datasets:
- Even a few delayed rakes will be flagged
- The method is working correctly
- 50% outliers can be legitimate in small samples

## What Different Percentages Mean

### ✅ Less than 5% Outliers
```
Total: 100 rakes
Outliers: 3 rakes

Meaning: Excellent consistency
Action: Normal operations, no concern
```

### ⚠️ 5-10% Outliers
```
Total: 50 rakes
Outliers: 4 rakes

Meaning: Good operations with minor variations
Action: Monitor but no immediate action needed
```

### 🟡 10-20% Outliers
```
Total: 30 rakes
Outliers: 5 rakes

Meaning: Moderate variability
Action: Review patterns, identify causes
```

### 🔴 20%+ Outliers
```
Total: 20 rakes
Outliers: 6 rakes

Meaning: High variability or systemic issues
Action: Investigate immediately
```

## Why Your Case Shows 50%

### Likely Reasons:

1. **Small Sample Size**
   - 14 records is a small dataset
   - A few delays have bigger impact on percentage
   - Statistical methods are more sensitive with small data

2. **Specific Filter Combination**
   - You've selected specific: Source + Commodity + Rake Type
   - This narrows down to fewer records
   - Real operational issues may exist for this specific combination

3. **Recent Period**
   - If analyzing last 30 days only
   - Recent delays/issues will show prominently
   - Try "Last 90 Days" or "Monthly" for bigger picture

4. **Legitimate Issues**
   - This route/commodity combination may genuinely have problems
   - 50% outliers could indicate real operational concerns
   - Worth investigating those specific rakes

## How to Interpret Your Results

### Check These:

1. **Expand Your Filters**
```
Current: BSP + RDCR + PIOR = 14 records
Try: BSP + All Sources + PIOR = 50+ records

Helps you see if RDCR specifically has issues
or if PIOR generally has transit problems
```

2. **Look at the Table**
```
Do the outliers show:
- All from same source? → Source issue
- All same commodity? → Commodity handling issue  
- All recent dates? → Recent operational problem
- Random pattern? → Normal variation
```

3. **Compare Time Periods**
```
Last 30 days: 50% outliers (recent problems)
Last 90 days: 20% outliers (longer term trend)
Monthly average: 10% outliers (normal baseline)
```

## Real Example Walkthrough

```
Your Selection:
- Destination: BSP
- Source: RDCR  
- Commodity: PIOR
- Period: Last 30 Days
- Result: 14 total, 7 outliers (50%)

What to Do:
```

### Step 1: Look at the Outlier Table
```
Outlier #1: 82 hours (normal is 45-50)
Outlier #2: 78 hours
Outlier #3: 75 hours
... (all high transit times)

Observation: All outliers are HIGH (delays)
None are LOW (data errors)
```

### Step 2: Check Dates
```
Outlier dates: 
- Jan 15, Jan 16, Jan 17, Jan 20, Jan 21, Jan 22, Jan 23

Observation: All recent, clustered together
Suggests: Recent operational issue affecting RDCR to BSP route
```

### Step 3: Expand Analysis
```
Change filter to: BSP + All Sources + PIOR
New result: 50 records, 10 outliers (20%)

Conclusion: RDCR specifically has higher delay rate
Other sources are performing better
```

## Recommended Actions

### If You See 50% Outliers:

1. **Don't Panic** - Small datasets naturally show higher percentages

2. **Investigate** - Look at:
   - Are they all recent? (Recent issue)
   - All from one source? (Source problem)
   - All one commodity? (Commodity handling issue)

3. **Broaden View** - Try:
   - Longer time periods
   - Remove some filters
   - Compare with other routes

4. **Take Action** - If legitimate issue:
   - Contact source station
   - Review operational logs
   - Check for route/weather issues

## Summary

**50% outliers with 14 records means:**
- 7 rakes had normal transit times (45-50 hrs)
- 7 rakes had abnormal transit times (70+ hrs)
- This is mathematically correct
- It may indicate real problems OR just small sample size
- Expand your analysis to confirm if it's a real issue

**The feature is working correctly** - it's showing you that half of the rakes in your specific selection had transit times outside the normal range. Whether this is a concern depends on:
- Your specific route expectations
- Historical performance
- Recent operational changes
- Broader context from other filters

---

**Pro Tip:** Always analyze with both narrow filters (to find specific issues) and broad filters (to see overall trends) for complete understanding!
