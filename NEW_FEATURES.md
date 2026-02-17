# New Features Documentation

This document describes newly added features beyond the main README.

## 🌙 Dark Mode

Toggle between light and dark themes using the button in the navigation bar (moon/sun icon).

### Features
- Optimized colors for both themes
- Automatic theme persistence (remembers your choice)
- Smooth transitions
- Works across all pages

### Usage
Click the theme toggle button (🌙/☀️) in the top navigation bar to switch between light and dark modes.

---

## 📅 Workout History

View all your completed workouts with detailed statistics.

### Features
- Chronological list of all completed workout sessions
- Per-workout statistics:
  - Total training volume (weight × reps)
  - Number of unique exercises performed
  - Total working sets completed
  - Workout duration in minutes
- Exercise breakdown showing set counts
- Clean, card-based layout

### Access
Click "History" in the navigation bar or the "Workout History" card on the home page.

---

## ⚖️ Plate Calculator

Calculate what plates to load on a barbell for any target weight.

### Features
- Support for multiple bar types (Olympic, Women's, Fixed, Custom)
- Customizable available plates
- Real-time calculation
- Visual breakdown of plates per side
- Total weight verification
- Warnings for inexact matches

### How to Use
1. Navigate to Tools → Plate Calculator from the home page
2. Enter your target weight
3. Select your bar type
4. Choose available plates
5. Click "Calculate"

The tool will show you exactly which plates to load on each side of the bar.

---

## 📊 Comprehensive Improvement Suggestions

See `SUGGESTED_IMPROVEMENTS.md` for a detailed analysis with 70+ suggested improvements across:
- User experience enhancements
- Advanced analytics
- Training-specific features
- Health integration
- Mobile and UX improvements
- Social and sharing features
- Technical improvements
- UI/UX polish
- Security and privacy
- Advanced features

See `IMPLEMENTATION_SUMMARY.md` for details on the implemented features.

---

## 🔧 For Developers

### File Structure
```
├── SUGGESTED_IMPROVEMENTS.md     # 70+ improvement suggestions
├── IMPLEMENTATION_SUMMARY.md     # Implementation details
├── templates/
│   ├── history.html              # Workout history page
│   └── plate_calculator.html     # Plate calculator tool
├── app.py                        # Added history and calculator routes
├── static/css/style.css          # Added dark mode styles
└── templates/base.html           # Added theme toggle
```

### New Routes
- `/history` - Workout history page
- `/tools/plate-calculator` - Plate calculator tool

### CSS Variables
Dark mode is implemented using CSS custom properties. The theme is controlled via `data-theme` attribute on the `<html>` element.

### Local Storage
Theme preference is stored in `localStorage` with key `theme` (values: `'light'` or `'dark'`).

---

**Last Updated:** February 17, 2026
