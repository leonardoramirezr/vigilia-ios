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
                    SummarySections(samples: samples, period: period)
                case (.average, .byWeekday):
                    WeekdaySummarySection(samples: samples, period: period)
                case (.evolution, _):
                    EvolutionSections(samples: samples, grouping: grouping, period: period, shownWeekdays: $shownWeekdays)
                }
            }
        }
        .navigationTitle("Estadísticas")
    }
}

// MARK: - Sections

/// How many wake-ups, then the average and percentiles of each measure.
private struct SummarySections: View {
    let samples: [WakeSample]
    let period: StatsPeriod

    var body: some View {
        Section {
            LabeledContent("Despertares", value: "\(samples.count)")
        } footer: {
            Text(period.footer)
        }
        ForEach(WakeMeasure.allCases) { measure in
            if let summary = WakeStatistics.summary(of: samples, measure) {
                MeasureSummarySection(measure: measure, summary: summary)
            }
        }
        Section {
            DisclosureGroup("¿Qué es un percentil?") {
                Text("Imagina tus despertares en fila, del más temprano al más tarde (o del más rápido al más lento). El percentil 10 es el que queda a una décima parte de la fila, el 50 justo a la mitad y el 90 a nueve décimas. A diferencia del promedio, un día raro casi no los mueve.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct MeasureSummarySection: View {
    let measure: WakeMeasure
    let summary: WakeSummary

    var body: some View {
        Section {
            VStack(spacing: 2) {
                Text(measure.text(summary.average))
                    .font(.system(size: 44, weight: .semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                Text("en promedio")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            ForEach(Percentile.all) { percentile in
                LabeledContent {
                    Text(measure.text(summary[keyPath: percentile.value]))
                        .monospacedDigit()
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(percentile.title)
                        Text("\(percentile.share) \(measure.percentileMeaning).")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Label(measure.title, systemImage: measure.icon)
        } footer: {
            Text(measure.footer)
        }
    }
}

private struct Percentile: Identifiable {
    let title: String
    /// The share of days at or below the value, to explain it.
    let share: String
    let value: KeyPath<WakeSummary, Double>

    var id: String { title }

    static let all = [
        Percentile(title: "Percentil 10", share: "1 de cada 10 días", value: \.p10),
        Percentile(title: "Percentil 50 (mediana)", share: "La mitad de los días", value: \.p50),
        Percentile(title: "Percentil 90", share: "9 de cada 10 días", value: \.p90),
    ]
}

private struct WeekdaySummarySection: View {
    let samples: [WakeSample]
    let period: StatsPeriod

    var body: some View {
        let byDay = Dictionary(grouping: samples, by: \.weekday)
        Section {
            ForEach(WeekdayPicker.orderedDays, id: \.self) { day in
                let name = WeekdayPicker.names[day - 1].capitalized
                if let daySamples = byDay[day] {
                    NavigationLink {
                        Form {
                            SummarySections(samples: daySamples, period: period)
                        }
                        .navigationTitle(name)
                    } label: {
                        LabeledContent {
                            MeasureValues(values: averages(of: daySamples))
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(name)
                                Text(daySamples.count == 1 ? "1 despertar" : "\(daySamples.count) despertares")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                } else {
                    LabeledContent(name) {
                        Text("Sin datos")
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Promedio por día")
        } footer: {
            Text("Toca un día para ver sus percentiles. \(period.footer)")
        }
    }

    private func averages(of samples: [WakeSample]) -> [WakeMeasure: Double] {
        var averages: [WakeMeasure: Double] = [:]
        for measure in WakeMeasure.allCases {
            averages[measure] = WakeStatistics.summary(of: samples, measure)?.average
        }
        return averages
    }
}

private struct EvolutionSections: View {
    let samples: [WakeSample]
    let grouping: StatsGrouping
    let period: StatsPeriod
    @Binding var shownWeekdays: Set<Int>

    var body: some View {
        let shown = grouping == .wholeWeek ? samples : samples.filter { shownWeekdays.contains($0.weekday) }
        let trends = WakeMeasure.allCases.map { measure in
            MeasureTrend(measure: measure, trend: WakeStatistics.trend(of: shown, measure, grouping: grouping, calendar: .current))
        }
        if grouping == .byWeekday {
            Section {
                WeekdayPicker(selection: $shownWeekdays)
            } header: {
                Text("Días en las gráficas")
            }
        }
        if shown.isEmpty {
            Section {
                Text("No hay despertares en los días elegidos.")
                    .foregroundStyle(.secondary)
            }
        } else {
            ForEach(trends) { entry in
                Section {
                    WakeTrendChart(trend: entry.trend, measure: entry.measure)
                        .frame(height: 240)
                        .padding(.vertical, 8)
                } header: {
                    Label(entry.measure.title, systemImage: entry.measure.icon)
                } footer: {
                    if entry.id == trends.first?.id {
                        Text("\(entry.measure.footer) \(entry.trend.resolution.caption) Mantén el dedo sobre una gráfica para ver cada valor.")
                    } else {
                        Text(entry.measure.footer)
                    }
                }
            }
            Section {
                DisclosureGroup("Ver datos") {
                    DataRows(trends: trends)
                }
            } footer: {
                Text(period.footer)
            }
        }
    }
}

private struct MeasureTrend: Identifiable {
    let measure: WakeMeasure
    let trend: WakeTrend

    var id: WakeMeasure { measure }
}

/// The table behind the charts: one row per point, with the three measures.
private struct DataRows: View {
    let trends: [MeasureTrend]

    var body: some View {
        // The trends come from the same wake-ups, so their points share dates and ids.
        let points = trends.first?.trend.points ?? []
        let resolution = trends.first?.trend.resolution ?? .day
        let values = trends.reduce(into: [String: [WakeMeasure: Double]]()) { values, entry in
            for point in entry.trend.points {
                values[point.id, default: [:]][entry.measure] = point.minute
            }
        }
        ForEach(points.reversed()) { point in
            LabeledContent {
                MeasureValues(values: values[point.id] ?? [:])
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(StatsFormat.label(for: point, resolution: resolution))
                    if point.count > 1 {
                        Text("promedio de \(point.count)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

/// The three measures of a weekday or a chart point, one per line.
private struct MeasureValues: View {
    let values: [WakeMeasure: Double]

    var body: some View {
        VStack(alignment: .trailing, spacing: 2) {
            ForEach(WakeMeasure.allCases) { measure in
                if let value = values[measure] {
                    HStack(spacing: 4) {
                        Text(measure.shortTitle)
                            .foregroundStyle(.secondary)
                        Text(measure.text(value))
                            .monospacedDigit()
                    }
                }
            }
        }
        .font(.callout)
    }
}

// MARK: - Chart

private struct WakeTrendChart: View {
    let trend: WakeTrend
    let measure: WakeMeasure
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
        let axis = WakeStatistics.axis(for: trend.points.map(\.minute), measure)
        // Markers help with a few points (and a lone point needs one to show up at all).
        let markers = trend.points.count <= 60
        Chart {
            ForEach(trend.points) { point in
                if markers {
                    LineMark(x: .value("Fecha", point.date), y: .value(measure.title, point.minute))
                        .foregroundStyle(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .symbol(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .symbolSize(40)
                        .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                } else {
                    LineMark(x: .value("Fecha", point.date), y: .value(measure.title, point.minute))
                        .foregroundStyle(by: .value("Día", StatsFormat.seriesName(point.weekday)))
                        .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                }
            }
            if isSingleLine, let average = trend.average {
                RuleMark(y: .value("Promedio", average))
                    .foregroundStyle(Color.secondary)
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    .annotation(position: .top, alignment: .leading) {
                        Text("Promedio \(measure.text(average))")
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
                        SelectionCard(points: selectedPoints, measure: measure, resolution: trend.resolution)
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
                        Text(measure.text(minute))
                    }
                }
            }
        }
        .chartXSelection(value: $selectedDate)
    }
}

private struct SelectionCard: View {
    let points: [WakePoint]
    let measure: WakeMeasure
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
                    Text(measure.text(point.minute))
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

    /// A duration in minutes: "45 s", "3 min 20 s", "25 min", "1 h 5 min".
    /// Seconds only matter for the first few minutes.
    static func duration(_ minutes: Double) -> String {
        let seconds = Int((max(0, minutes) * 60).rounded())
        if seconds == 0 { return "0 min" }
        if seconds < 60 { return "\(seconds) s" }
        if seconds < 10 * 60 {
            return seconds % 60 == 0 ? "\(seconds / 60) min" : "\(seconds / 60) min \(seconds % 60) s"
        }
        let total = Int((Double(seconds) / 60).rounded())
        if total < 60 { return "\(total) min" }
        return total % 60 == 0 ? "\(total / 60) h" : "\(total / 60) h \(total % 60) min"
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
        case .average: return "Resumen"
        case .evolution: return "Gráficas"
        }
    }
}

private extension WakeMeasure {
    var title: String {
        switch self {
        case .alarmTime: return "Hora en que sonó"
        case .offTime: return "Hora en que la apagaste"
        case .timeToOff: return "Tiempo en apagarla"
        }
    }

    /// Next to a value, where the three measures are listed together.
    var shortTitle: String {
        switch self {
        case .alarmTime: return "Sonó"
        case .offTime: return "Apagada"
        case .timeToOff: return "Tardaste"
        }
    }

    var icon: String {
        switch self {
        case .alarmTime: return "alarm"
        case .offTime: return "checkmark.circle"
        case .timeToOff: return "timer"
        }
    }

    var footer: String {
        switch self {
        case .alarmTime: return "La primera vez que sonó la alarma, sin contar cuando vuelve a sonar."
        case .offTime: return "Cuando completaste el reto y la alarma se apagó."
        case .timeToOff: return "Desde que sonó por primera vez hasta que completaste el reto."
        }
    }

    /// Completes "1 de cada 10 días …" to explain a percentile.
    var percentileMeaning: String {
        switch self {
        case .alarmTime: return "sonó a esta hora o antes"
        case .offTime: return "la apagaste a esta hora o antes"
        case .timeToOff: return "tardaste este tiempo o menos"
        }
    }

    func text(_ value: Double) -> String {
        isTimeOfDay ? Clock.text(value) : StatsFormat.duration(value)
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
        return "Cuenta las alarmas que apagaste con el reto \(scope). Las pruebas no cuentan."
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
