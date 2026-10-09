import Charts
import SwiftUI
import UIKit

/// Wake-up statistics. The three pickers are independent, so every combination of
/// statistic, grouping and period works.
struct StatsView: View {
    @EnvironmentObject private var controller: AlarmController
    @AppStorage("stats.metric") private var metric = StatsMetric.average
    @AppStorage("stats.grouping") private var grouping = StatsGrouping.wholeWeek
    @AppStorage("stats.period") private var period = StatsPeriod.month
    @State private var shownWeekdays = Set(1...7)

    var body: some View {
        let samples = WakeStatistics.samples(
            from: controller.state.history, period: period, now: controller.now, calendar: .current)
        Form {
            Section {
                SegmentedChoice(title: "Estadística", selection: $metric, options: StatsMetric.allCases) { $0.title }
                SegmentedChoice(title: "Por", selection: $grouping, options: StatsGrouping.allCases) { $0.title }
                SegmentedChoice(title: "Contando", selection: $period, options: StatsPeriod.allCases) { $0.title }
            }
            if samples.isEmpty {
                Section {
                    ContentUnavailableView(
                        "Sin despertares",
                        systemImage: "chart.xyaxis.line",
                        description: Text(period.emptyMessage))
                }
            } else {
                switch (metric, grouping) {
                case (.average, .wholeWeek):
                    AverageSection(samples: samples, period: period)
                case (.average, .byWeekday):
                    WeekdayAverageSection(samples: samples, period: period)
                case (.evolution, _):
                    EvolutionSections(samples: samples, grouping: grouping, period: period, shownWeekdays: $shownWeekdays)
                }
            }
        }
        .navigationTitle("Estadísticas")
    }
}

// MARK: - Sections

private struct AverageSection: View {
    let samples: [WakeSample]
    let period: StatsPeriod

    var body: some View {
        if let summary = WakeStatistics.summary(of: samples.map(\.minuteOfDay)) {
            Section {
                VStack(spacing: 4) {
                    Text(Clock.text(summary.average))
                        .font(.system(size: 56, weight: .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.5)
                    Text("hora promedio de despertar")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                LabeledContent("Despertares", value: "\(summary.count)")
                LabeledContent("Más temprano", value: Clock.text(summary.earliest))
                LabeledContent("Más tarde", value: Clock.text(summary.latest))
            } footer: {
                Text(period.footer)
            }
        }
    }
}

private struct WeekdayAverageSection: View {
    let samples: [WakeSample]
    let period: StatsPeriod

    var body: some View {
        let byDay = WakeStatistics.summaryByWeekday(samples)
        Section {
            ForEach(WeekdayPicker.orderedDays, id: \.self) { day in
                LabeledContent {
                    if let summary = byDay[day] {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(Clock.text(summary.average))
                                .monospacedDigit()
                            Text(summary.count == 1 ? "1 despertar" : "\(summary.count) despertares")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Text("Sin datos")
                            .foregroundStyle(.secondary)
                    }
                } label: {
                    Text(WeekdayPicker.names[day - 1].capitalized)
                }
            }
        } header: {
            Text("Hora promedio por día")
        } footer: {
            Text(period.footer)
        }
    }
}

private struct EvolutionSections: View {
    let samples: [WakeSample]
    let grouping: StatsGrouping
    let period: StatsPeriod
    @Binding var shownWeekdays: Set<Int>

    var body: some View {
        let shown = grouping == .wholeWeek ? samples : samples.filter { shownWeekdays.contains($0.weekday) }
        let trend = WakeStatistics.trend(of: shown, grouping: grouping, calendar: .current)
        Section {
            if grouping == .byWeekday {
                WeekdayPicker(selection: $shownWeekdays)
            }
            if trend.points.isEmpty {
                Text("No hay despertares en los días elegidos.")
                    .foregroundStyle(.secondary)
            } else {
                WakeTrendChart(trend: trend)
                    .frame(height: 260)
                    .padding(.vertical, 8)
            }
        } header: {
            Text("Evolución de la hora de despertar")
        } footer: {
            Text("\(trend.resolution.caption) Mantén el dedo sobre la gráfica para ver cada valor. \(period.footer)")
        }
        if !trend.points.isEmpty {
            Section {
                DisclosureGroup("Ver datos") {
                    ForEach(trend.points.reversed()) { point in
                        LabeledContent {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(Clock.text(point.minute))
                                    .monospacedDigit()
                                if point.count > 1 {
                                    Text("promedio de \(point.count)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        } label: {
                            Text(StatsFormat.label(for: point, resolution: trend.resolution))
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Chart

private struct WakeTrendChart: View {
    let trend: WakeTrend
    @State private var selectedDate: Date? = nil

    /// The lines on the chart: the whole week, or the weekdays that have data.
    private var series: [Int?] {
        let present = Set(trend.points.map(\.weekday))
        if present.contains(nil) { return [nil] }
        return WeekdayPicker.orderedDays.filter { present.contains($0) }
    }

    private var isSingleLine: Bool { series == [nil] }

    /// Every point at the date nearest to the finger.
    private var selectedPoints: [WakePoint] {
        guard let selectedDate,
              let nearest = trend.points.min(by: {
                  abs($0.date.timeIntervalSince(selectedDate)) < abs($1.date.timeIntervalSince(selectedDate))
              })
        else { return [] }
        return trend.points.filter { $0.date == nearest.date }
    }

    var body: some View {
        let axis = WakeStatistics.axis(for: trend.points.map(\.minute))
        // Markers help with a few points (and a lone point needs one to show up at all).
        let markers = trend.points.count <= 60
        Chart {
            ForEach(trend.points) { point in
                if markers {
                    LineMark(x: .value("Fecha", point.date), y: .value("Hora", point.minute))
                        .foregroundStyle(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .symbol(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .symbolSize(40)
                        .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                } else {
                    LineMark(x: .value("Fecha", point.date), y: .value("Hora", point.minute))
                        .foregroundStyle(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                }
            }
            if isSingleLine, let average = trend.average {
                RuleMark(y: .value("Promedio", average))
                    .foregroundStyle(Color.secondary)
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    .annotation(position: .top, alignment: .leading) {
                        Text("Promedio \(Clock.text(average))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
            }
            if let selected = selectedPoints.first {
                RuleMark(x: .value("Fecha", selected.date))
                    .foregroundStyle(Color.secondary.opacity(0.5))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    .annotation(
                        position: .top, spacing: 4,
                        overflowResolution: .init(x: .fit(to: .chart), y: .fit(to: .chart))
                    ) {
                        SelectionCard(points: selectedPoints, resolution: trend.resolution)
                    }
            }
        }
        .chartForegroundStyleScale(
            domain: series.map { StatsFormat.seriesName($0) },
            range: series.map { StatsPalette.color(for: $0) })
        .chartSymbolScale(
            domain: series.map { StatsFormat.seriesName($0) },
            range: series.map { StatsPalette.symbol(for: $0) })
        .chartLegend(isSingleLine ? .hidden : .visible)
        .chartYScale(domain: axis.lower...axis.upper)
        .chartYAxis {
            AxisMarks(position: .leading, values: .stride(by: axis.step)) { value in
                AxisGridLine()
                AxisValueLabel {
                    if let minute = value.as(Double.self) {
                        Text(Clock.text(minute))
                    }
                }
            }
        }
        .chartXSelection(value: $selectedDate)
    }
}

private struct SelectionCard: View {
    let points: [WakePoint]
    let resolution: WakeTrend.Resolution

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let first = points.first {
                Text(StatsFormat.dateText(first.date, resolution: resolution))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(points) { point in
                HStack(spacing: 6) {
                    Text(Clock.text(point.minute))
                        .font(.callout.weight(.semibold))
                        .monospacedDigit()
                    if let weekday = point.weekday {
                        Capsule()
                            .fill(StatsPalette.color(for: weekday))
                            .frame(width: 12, height: 3)
                        Text(WeekdayPicker.names[weekday - 1])
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(8)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
        .shadow(color: .black.opacity(0.12), radius: 4, y: 1)
    }
}

// MARK: - Controls

private struct SegmentedChoice<Option: Hashable & Identifiable>: View {
    let title: String
    @Binding var selection: Option
    let options: [Option]
    let label: (Option) -> String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            Picker(title, selection: $selection) {
                ForEach(options) { option in
                    Text(label(option)).tag(option)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Formatting

enum Clock {
    /// Minutes after midnight as a time of day ("7:05", or "7:05 a.m." with a
    /// 12-hour clock). Values past midnight wrap around.
    static func text(_ minute: Double) -> String {
        let total = Int(WakeStatistics.normalized(minute.rounded()))
        let date = DateComponents(calendar: .current, year: 2001, month: 1, day: 1, hour: total / 60, minute: total % 60).date
        return (date ?? .now).formatted(date: .omitted, time: .shortened)
    }
}

private enum StatsFormat {
    static func seriesName(_ weekday: Int?) -> String {
        weekday.map { WeekdayPicker.names[$0 - 1].capitalized } ?? "Toda la semana"
    }

    static func dateText(_ date: Date, resolution: WakeTrend.Resolution) -> String {
        switch resolution {
        case .day: return date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        case .week: return "Semana del \(date.formatted(.dateTime.day().month(.abbreviated)))"
        case .month: return date.formatted(.dateTime.month(.wide).year())
        }
    }

    static func label(for point: WakePoint, resolution: WakeTrend.Resolution) -> String {
        let date = dateText(point.date, resolution: resolution)
        guard let weekday = point.weekday, resolution != .day else { return date }
        return "\(seriesName(weekday)) · \(date.prefix(1).lowercased() + date.dropFirst())"
    }
}

private enum StatsPalette {
    /// The validated categorical palette, in order; the dark steps are tuned for
    /// dark backgrounds. A weekday keeps its color whatever days are shown.
    private static let slots: [(light: UInt32, dark: UInt32)] = [
        (0x2A78D6, 0x3987E5), // blue
        (0xEB6834, 0xD95926), // orange
        (0x1BAF7A, 0x199E70), // aqua
        (0xEDA100, 0xC98500), // yellow
        (0xE87BA4, 0xD55181), // magenta
        (0x008300, 0x008300), // green
        (0x4A3AA7, 0x9085E9), // violet
    ]
    /// A second channel for telling the weekday lines apart.
    private static let symbols: [BasicChartSymbolShape] = [.circle, .square, .triangle, .diamond, .pentagon, .cross, .plus]

    /// nil is the whole week: orange, like the rest of the app.
    static func color(for weekday: Int?) -> Color {
        guard let weekday else { return color(slots[1]) }
        return color(slots[WeekdayPicker.orderedDays.firstIndex(of: weekday) ?? 0])
    }

    static func symbol(for weekday: Int?) -> BasicChartSymbolShape {
        guard let weekday else { return .circle }
        return symbols[WeekdayPicker.orderedDays.firstIndex(of: weekday) ?? 0]
    }

    private static func color(_ slot: (light: UInt32, dark: UInt32)) -> Color {
        Color(UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? slot.dark : slot.light
            return UIColor(
                red: CGFloat(hex >> 16 & 0xFF) / 255,
                green: CGFloat(hex >> 8 & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: 1)
        })
    }
}

private extension StatsMetric {
    var title: String {
        switch self {
        case .average: return "Hora promedio"
        case .evolution: return "Gráfica de línea"
        }
    }
}

private extension StatsGrouping {
    var title: String {
        switch self {
        case .byWeekday: return "Día de la semana"
        case .wholeWeek: return "Toda la semana"
        }
    }
}

private extension StatsPeriod {
    var title: String {
        switch self {
        case .always: return "Siempre"
        case .year: return "1 año"
        case .month: return "1 mes"
        case .week: return "1 semana"
        }
    }

    var footer: String {
        let scope: String
        switch self {
        case .always: scope = "desde el primer despertar registrado"
        case .year: scope = "en el último año"
        case .month: scope = "en el último mes"
        case .week: scope = "en los últimos 7 días"
        }
        return "Cuenta la hora a la que apagaste la alarma con el reto, \(scope). Las pruebas no cuentan."
    }

    var emptyMessage: String {
        switch self {
        case .always: return "Todavía no has apagado ninguna alarma con el reto. Las pruebas no cuentan."
        case .year: return "No apagaste ninguna alarma en el último año."
        case .month: return "No apagaste ninguna alarma en el último mes."
        case .week: return "No apagaste ninguna alarma en los últimos 7 días."
        }
    }
}

private extension WakeTrend.Resolution {
    var caption: String {
        switch self {
        case .day: return "Cada punto es un despertar."
        case .week: return "Cada punto es el promedio de una semana."
        case .month: return "Cada punto es el promedio de un mes."
        }
    }
}
