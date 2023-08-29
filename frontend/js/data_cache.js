import { MIN_CTIME, MAX_FETCH_ITEMS, API_HOURS, API_MINUTES } from "./constants.js"

export default class DataCache {
    constructor(perMinute) {
        this._perMinute = perMinute
        this._cache = {}
        this._pending = new Set()
        this._pulling = {
            'doing': false,
            'begin': MIN_CTIME,
            'end': MIN_CTIME
        }
        this._fetching = {
            'begin': MIN_CTIME,
            'end': MIN_CTIME
        }
        this._updateCbs = []
    }

    addCallback(cb) {
        this._updateCbs.push(cb)
    }

    _pullServerData(begin, end) {
        this._pulling = {
            'doing': true,
            'begin': begin,
            'end': end
        }
        window.fetch(`${this._perMinute ? API_MINUTES : API_HOURS}&begin=${begin}&end=${end}`, { method: 'GET', mode: 'cors' })
            .then(response => response.json())
            .then(data => {
                data.forEach(ele => {
                    let t = new Date(ele['ctime'] * 1000)
                    this._cache[ele['ctime']] = {
                        'epoch': ele['ctime'],
                        'show': this._perMinute ? `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 5)}` : `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 2)}`,
                        'total': ele['total'],
                        'snr': ele['snr'],
                        'countries': ele['countries']
                    }
                })
                for (let i = this._pulling['begin']; i <= this._pulling['end']; i += this._perMinute ? 60 : 3600) {
                    if (this._cache[i] === undefined) {
                        let t = new Date(i * 1000)
                        this._cache[i] = {
                            'epoch': i,
                            'show': this._perMinute ? `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 5)}` : `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 2)}`,
                            'total': -1,
                            'snr': 0,
                            'countries': {}
                        }
                    }
                    this._pending.delete(i)
                }
                this._pulling['doing'] = false
                this._pendingCheck()
                //debug -->
                // let tt = []
                // Object.keys(this._cache).forEach(k => {
                //     tt.push(this._cache[k]['total'])
                // })
                // console.log(tt)
                //<-- debug
                this._updateCbs.forEach(cb => cb())
            })
            .catch(err => {
                console.error('Error when fetch from server minutes api:')
                console.error(err)
                this._pulling['doing'] = false
            })
    }

    _pendingCheck() {
        if (this._pulling['doing']) return

        let begin = Number.MAX_VALUE, end = 0
        this._pending.forEach(i => {
            if (i < this._fetching['begin'] || i > this._fetching['end']) return
            begin = Math.min(begin, i)
            end = Math.max(end, i)
        })
        end = Math.min(end, begin + (this._perMinute ? 60 : 3600) * (MAX_FETCH_ITEMS - 1))
        if (begin <= end && end > 0) {
            this._pullServerData(begin, end)
        }
    }

    fetchTimeData(begin, end) {
        //debug ->
        // let debug_bt = new Date(begin * 1000)
        // let debug_et = new Date(end * 1000)
        // console.log(`fetchTimeData: ${begin} - ${end} (${debug_bt.toLocaleString()} - ${debug_et.toLocaleString()})`)
        //<- debug

        let now = Math.round(Date.now() / 1000)
        if (Number.isNaN(begin) || begin < 0 || begin > now) {
            console.error(`bad begin param when call fetchTimeData(${begin}, ${end})`)
            return []
        }
        if (end !== undefined) {
            if (Number.isNaN(end) || (begin > end) || end > now) {
                console.error(`bad end param when call fetchTimeData(${begin}, ${end})`)
                return []
            }
        } else {
            end = now
        }
        begin = Math.round(begin - begin % (this._perMinute ? 60 : 3600))
        end = Math.round(end - end % (this._perMinute ? 60 : 3600))

        this._fetching = {
            'begin': begin,
            'end': end
        }

        let rst = []
        for (let i = begin; i <= end; i += (this._perMinute ? 60 : 3600)) {
            if (this._cache[i] === undefined) {
                let t = new Date(i * 1000)
                this._pending.add(i)
                rst.push({
                    'epoch': i,
                    'show': this._perMinute ? `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 5)}` : `${t.getMonth() + 1}/${t.getDate()} ${t.toLocaleTimeString().substring(0, 2)}`,
                    'total': -1,
                    'snr': 0,
                    'countries': {}
                })
            } else {
                rst.push(this._cache[i])
            }
        }

        this._pendingCheck()
        return rst
    }

    dataRangeToCountries(dataRange) {
        let rst = {}
        dataRange.forEach(d => {
            Object.keys(d['countries']).forEach(c => {
                if (rst[c] === undefined) {
                    rst[c] = d['countries'][c]
                } else {
                    rst[c] += d['countries'][c]
                }
            })
        })
        return rst
    }
}
