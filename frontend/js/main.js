import countriesGeoJson from './countries_geo.js';
import BarChartUpdater from './BarChartUpdater.js';
import DataCache from './data_cache.js';

const minuteCache = new DataCache(true)
const hourCache = new DataCache(false)

//load geojson
echarts.registerMap('WORLD', countriesGeoJson)

//show charts
const barchart = echarts.init(document.getElementById('barchart'), 'white', { renderer: 'canvas' })
const countrychart = echarts.init(document.getElementById('countrychart'), 'white', { renderer: 'canvas' })
new BarChartUpdater(barchart, countrychart, minuteCache, hourCache)
