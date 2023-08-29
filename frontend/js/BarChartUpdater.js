import { cty2geo } from "./countries_geo.js"
import { MIN_CTIME, MAX_FETCH_ITEMS } from "./constants.js"
export default class BarChartUpdater {
    constructor(barChart, countryChart, minuteCache, hourCache) {
        this._barChart = barChart
        this._countryChart = countryChart
        this._minuteCache = minuteCache
        this._hourCache = hourCache
        this._rebaseTimer = null

        let now = Math.round(Date.now() / 1000)
        now = now - now % 60
        this._range = {
            begin: now - MAX_FETCH_ITEMS * 60,
            end: now
        }
        this._view = {
            type: 'minute', // minute | hour | day 
            start: 50,
            end: 100
        }
        let bt = new Date(this._range.begin * 1000)
        let et = new Date(this._range.end * 1000)
        this._bcOption = {
            'title': {
                'text': 'ft8 signal monitor',
                'subtext': 'count per minute'
            },
            'dataZoom': [{
                'type': 'inside',
                'start': 50,
                'end': 100
            }, {
                'type': 'slider',
                'start': 50,
                'end': 100
            }],
            'dataset': {
                'source': []
            },
            'tooltip': {
                'formatter': params => {
                    const t = params['value'][0]
                    const total = params['value'][1] === -1 ? 'offline' : params['value'][1]
                    const snr = params['value'][1] === -1 ? 'offline' : params['value'][2]
                    return `${t}<br/>total: ${total}<br/>snr: ${snr}`
                }
            },
            'xAxis': { 'type': 'category' },
            'yAxis': {
                'min': -1,
                'minInterval': 1,
                'max': value => {
                    return Math.max(value.max, 10)
                }
            },
            'series': [{
                'type': 'bar',
                'itemStyle': {
                    'color': param => {
                        return '#' + this._snr2hex(param.value[2])
                    }
                }
            }]
        }

        this._ccOption = {
            title: {
                text: 'count by country',
                subtext: 'ft8mon',
            },
            tooltip: {
                trigger: 'item',
                showDelay: 0,
                transitionDuration: 0.2
            },
            visualMap: {
                left: '10%',
                bottom: '15%',
                min: 1,
                max: 100,
                inRange: {
                    color: [
                        '#313695',
                        '#4575b4',
                        '#74add1',
                        '#abd9e9',
                        '#e0f3f8',
                        '#ffffbf',
                        '#fee090',
                        '#fdae61',
                        '#f46d43',
                        '#d73027',
                        '#a50026'
                    ]
                },
                text: ['High', 'Low'],
                calculable: false
            },
            toolbox: {
                show: true,
                //orient: 'vertical',
                right: '10%',
                top: 'top',
                feature: {
                    dataView: {},
                }
            },
            series: [
                {
                    name: 'signal total',
                    type: 'map',
                    roam: true,
                    map: 'WORLD',
                    emphasis: {
                        label: {
                            show: true
                        }
                    },
                    data: []
                }
            ]
        }

        barChart.on('datazoom', params => {
            let start = 0, end = 100
            if (params.batch !== undefined && params.batch.length > 0) {
                start = params.batch[params.batch.length - 1]['start']
                end = params.batch[params.batch.length - 1]['end']
            } else {
                start = params.start
                end = params.end
            }
            this._onDataZoom(start, end)
        })
        window.addEventListener('resize', function () {
            barChart.resize()
            countryChart.resize()
        })

        minuteCache.addCallback(() => this._onDataArrival())
        hourCache.addCallback(() => this._onDataArrival())

        this._onDataArrival()

        this._refreshCountryChart()
    }

    _snr2hex(snr) {
        snr += 10
        if (snr <= 0) {
            if (snr <= -14) return 'ffeeee'
            return 'ff' + Number(Math.floor(-1 * snr)).toString(16).repeat(4)
        } else {
            if (snr >= 14) return '110000'
            return Number(15 - Math.floor(snr)).toString(16).repeat(2) + '0000'
        }
    }

    _onDataZoom(start, end) {
        this._view['start'] = start
        this._view['end'] = end
        if (this._rebaseTimer !== null) {
            window.clearTimeout(this._rebaseTimer)
        }
        this._rebaseTimer = window.setTimeout(() => {
            this._checkRerange(start, end)
        }, 1000)

        this._refreshCountryChart()
    }

    _refreshCountryChart() {
        let cvs = this._range['begin'] + (this._range['end'] - this._range['begin']) * this._view['start'] / 100
        let cve = this._range['begin'] + (this._range['end'] - this._range['begin']) * this._view['end'] / 100
        let bt = new Date(cvs * 1000)
        let et = new Date(cve * 1000)
        if (this._view['type'] === 'day') {
            this._ccOption['title']['subtext'] = `${bt.getFullYear()}/${bt.getMonth() + 1}/${bt.getDate()} - ${et.getFullYear()}/${et.getMonth() + 1}/${et.getDate()}}`
        } else {
            this._ccOption['title']['subtext'] = `${bt.getMonth() + 1}/${bt.getDate()} ${bt.toLocaleTimeString().substring(0, 5)} - ${et.getMonth() + 1}/${et.getDate()} ${et.toLocaleTimeString().substring(0, 5)}`
        }
        let cmax = 10
        const cdata = {}
        let vbi = Math.ceil(this._bcOption['dataset']['source'].length * this._view['start'] / 100)
        let vei = Math.ceil(this._bcOption['dataset']['source'].length * this._view['end'] / 100)
        for (let i = vbi; i < vei; i++) {
            let dc = this._bcOption['dataset']['source'][i]
            Object.keys(dc[3]).forEach(k => {
                if (cdata[k] === undefined) cdata[k] = 0
                cdata[k] += dc[3][k]
            })
        }
        const l = []
        Object.keys(cdata).forEach(k => {
            cmax = Math.max(cmax, cdata[k])
            l.push({
                'name': cty2geo[k] === undefined ? k : cty2geo[k],
                'value': cdata[k]
            })
        })
        this._ccOption['series'][0]['data'] = l

        this._ccOption['visualMap']['max'] = cmax

        this._countryChart.setOption(this._ccOption)
    }

    _checkRerange(start, end) {
        let needRerange = false
        let currentView = {
            start: this._range['begin'] + (this._range['end'] - this._range['begin']) * start / 100,
            end: this._range['begin'] + (this._range['end'] - this._range['begin']) * end / 100
        }
        let newViewType = 'minute'
        if (currentView.end - currentView.start > 3600 * 24 * 7) {
            newViewType = 'day'
        } else if (currentView.end - currentView.start > 3600 * 12) {
            newViewType = 'hour'
        }
        let newRangeStart = this._range['begin']
        let newRangeEnd = this._range['end']
        if (start < 10 && this._range['begin'] > MIN_CTIME) {
            newRangeStart = this._range['begin'] - (newViewType === 'minute' ? MAX_FETCH_ITEMS * 60 : MAX_FETCH_ITEMS * 3600)
            newRangeEnd = this._range['end']
            needRerange = true
        }
        if (end > 90) {
            newRangeEnd = this._range['end'] + (newViewType === 'minute' ? MAX_FETCH_ITEMS * 60 : MAX_FETCH_ITEMS * 3600)
            let now = Math.round(Date.now() / 1000)
            newRangeEnd = Math.min(newRangeEnd, now)
            if (newRangeStart == null) {
                newRangeStart = this._range['begin']
            }
            needRerange = true
        }
        if (newViewType !== this._view['type']) {
            needRerange = true
        }

        if (needRerange) this._rerange(newViewType, newRangeStart, newRangeEnd)
    }

    _rerange(viewType, newRangeStart, newRangeEnd) {
        let cvs = this._range['begin'] + (this._range['end'] - this._range['begin']) * this._view['start'] / 100
        let cve = this._range['begin'] + (this._range['end'] - this._range['begin']) * this._view['end'] / 100

        let data = []
        let start = null
        let end = null

        if (viewType === 'minute') {
            this._bcOption['title']['subtext'] = 'count per minute'

            let ws = cve - cvs
            if ((newRangeEnd - newRangeStart) > 3 * ws && (newRangeEnd - newRangeStart) > 3 * 60 * MAX_FETCH_ITEMS) {
                let now = Math.round(Date.now() / 1000)
                newRangeStart = cvs - Math.max(60 * MAX_FETCH_ITEMS, ws)
                newRangeEnd = cve + Math.max(60 * MAX_FETCH_ITEMS, ws)
                newRangeEnd = Math.min(now, newRangeEnd)
            }
            let rst = this._minuteCache.fetchTimeData(newRangeStart, newRangeEnd)
            rst.forEach(item => {
                start = start === null ? item['epoch'] : Math.min(start, item['epoch'])
                end = end === null ? item['epoch'] : Math.max(end, item['epoch'])
                data.push([
                    item['show'],
                    item['total'],
                    item['snr'],
                    item['countries']
                ])
            })
            if (start === null || end === null) {
                //debug
                console.error(`_rerange got empty cache data(in ${viewType}): ${newRangeStart}-${newRangeEnd}`)
                return
            }
        } else if (viewType === 'hour') {
            this._bcOption['title']['subtext'] = 'count per hour'

            let rst = this._hourCache.fetchTimeData(newRangeStart, newRangeEnd)
            rst.forEach(item => {
                start = start === null ? item['epoch'] : Math.min(start, item['epoch'])
                end = end === null ? item['epoch'] : Math.max(end, item['epoch'])
                data.push([
                    item['show'],
                    item['total'],
                    item['snr'],
                    item['countries']
                ])
            })
            if (start === null || end === null) {
                //debug
                console.error(`_rerange got empty cache data(in ${viewType}): ${newRangeStart}-${newRangeEnd}`)
                return
            }
        } else { // day
            this._bcOption['title']['subtext'] = 'count per day'

            let rst = this._hourCache.fetchTimeData(newRangeStart, newRangeEnd)
            let tl = []
            let tm = {}
            rst.forEach(item => {
                let tday = item['epoch'] - item['epoch'] % (24 * 3600)
                let sday = new Date(tday * 1000)
                if (tm[tday] === undefined) {
                    tl.push(tday)
                    tm[tday] = {
                        'hct': 0,
                        'show': `${sday.getFullYear()}/${sday.getMonth() + 1}/${sday.getDate()}`,
                        'total': -1,
                        'snr': 0,
                        'countries': {}
                    }
                }
                tm[tday]['hct'] += 1
                if (item['total'] > -1) {
                    if (tm[tday]['total'] === -1) tm[tday]['total'] = 0
                    tm[tday]['total'] += item['total']
                }
                tm[tday]['snr'] += item['total'] === -1 ? 0 : item['total'] * item['snr']
                Object.keys(item['countries']).forEach(c => {
                    if (tm[tday]['countries'][c] === undefined) tm[tday]['countries'][c] = 0
                    tm[tday]['countries'][c] += item['countries'][c]
                })
            })
            tl.forEach(tday => {
                if (tm[tday]['hct'] === 24) {
                    start = start === null ? tday : Math.min(start, tday)
                    end = end === null ? tday : Math.max(end, tday)
                    data.push([
                        tm[tday]['show'],
                        tm[tday]['total'],
                        Math.round(tm[tday]['snr'] / tm[tday]['total']),
                        tm[tday]['countries']
                    ])
                }
            })
            if (tl.length == 0) {
                //debug
                console.error(`_rerange got empty data(in ${viewType}): ${newRangeStart}-${newRangeEnd}`)
                return
            }
        }

        if (start === null || end === null) {
            //debug
            console.error(`_rerange got null start/end(in ${viewType}): ${newRangeStart}-${newRangeEnd}`)
            return
        }
        let dzs = Math.max(Math.round((cvs - start) / (end - start) * 100), 0)
        let dze = Math.min(Math.round(100 - (end - cve) / (end - start) * 100), 100)
        for (let i = 0; i < 2; i++) {
            this._bcOption['dataZoom'][i]['start'] = dzs
            this._bcOption['dataZoom'][i]['end'] = dze
        }
        this._bcOption['dataset']['source'] = data
        this._range = {
            'begin': start,
            'end': end
        }
        this._view = {
            'type': viewType,
            'start': dzs,
            'end': dze
        }
        this._barChart.setOption(this._bcOption)
    }

    _onDataArrival() {
        this._rerange(this._view['type'], this._range['begin'], this._range['end'])
    }
}
