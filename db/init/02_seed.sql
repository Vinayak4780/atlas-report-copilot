USE atlas;

-- R-101..R-103 and their metrics come from Appendix A of the brief (unchanged).
-- R-104..R-106 are additional synthetic reports so the corpus has 6 reports.
INSERT INTO reports (id, title, publisher, published, sector, market, region, access, keywords, summary) VALUES
('R-101', 'Global Smart Water Meter Market 2025', 'CMR', '2025-03-10', 'Utilities', 'Smart water meters', 'Global', 'paid',
 'water meter,water metering,smart water,ami water,amr water',
 'Global market sizing and forecast for smart water meters covering hardware, software and services, with regional splits.'),
('R-102', 'Smart Water Metering: Industry Outlook 2024', 'Aquila Insights (third party)', '2024-06-18', 'Utilities', 'Smart water meters', 'Global', 'public excerpt',
 'water meter,water metering,smart water,ami water,amr water',
 'Third-party outlook on AMR/AMI smart water meter hardware shipments and revenue; excludes software and services.'),
('R-103', 'Residential Water Purifier Market 2025', 'CMR', '2025-01-22', 'Consumer Durables', 'Residential water purifiers', 'Global', 'paid',
 'water purifier,purifier,water filter,ro purifier,water purification',
 'Global sizing and forecast for household water purifiers (RO, UV, gravity and filter systems) by region and channel.'),
('R-104', 'Asia-Pacific Smart Electricity Meter Market 2025', 'CMR', '2025-02-14', 'Utilities', 'Smart electricity meters', 'APAC', 'paid',
 'electricity meter,electric meter,smart electricity,power meter,energy meter',
 'Asia-Pacific sizing and forecast for smart electricity meters, with country-level analysis of rollout programmes.'),
('R-105', 'Global EV Charging Infrastructure Market 2025', 'CMR', '2025-04-02', 'Energy', 'EV charging infrastructure', 'Global', 'paid',
 'ev charging,charging infrastructure,charging station,charger,electric vehicle',
 'Global sizing and forecast for public and private EV charging hardware, software and installation services.'),
('R-106', 'Smart Home Appliances Market Outlook 2025', 'CMR', '2025-05-20', 'Consumer Durables', 'Smart home appliances', 'Global', 'paid',
 'smart home,home appliance,smart appliance,connected appliance',
 'Global sizing and forecast for connected major and small household appliances by product type and region.');

INSERT INTO market_metrics (report_id, market, metric, region, period_start, period_end, value, unit, scope_note, page) VALUES
('R-101', 'Smart water meters', 'market_size',    'Global', 2024, 2024, 4.21, 'USD_B', 'Includes hardware, software and services', 8),
('R-101', 'Smart water meters', 'cagr',           'Global', 2025, 2030, 11.2, 'PCT',   'Forecast period stated as 2025-2030', 8),
('R-101', 'Smart water meters', 'regional_share', 'APAC',   2024, 2024, 38.0, 'PCT',   'Share of global market size', 8),
('R-102', 'Smart water meters', 'market_size',    'Global', 2024, 2024, 3.87, 'USD_B', 'AMR / AMI hardware only', 14),
('R-102', 'Smart water meters', 'cagr',           'Global', 2024, 2029, 9.8,  'PCT',   'Different forecast window from R-101', 14),
('R-102', 'Smart water meters', 'regional_share', 'APAC',   2024, 2024, 41.0, 'PCT',   'Share of hardware market', 14),
('R-103', 'Residential water purifiers', 'market_size',    'Global', 2024, 2024, 28.6, 'USD_B', 'Household RO, UV, gravity and filter purifiers; excludes commercial units', 4),
('R-103', 'Residential water purifiers', 'cagr',           'Global', 2025, 2030, 8.3,  'PCT',   'Forecast period 2025-2030', 5),
('R-103', 'Residential water purifiers', 'regional_share', 'APAC',   2024, 2024, 44.0, 'PCT',   'Share of global market size', 6),
('R-104', 'Smart electricity meters', 'market_size',    'APAC',  2024, 2024, 9.6,  'USD_B', 'Asia-Pacific only; meters plus communication modules', 5),
('R-104', 'Smart electricity meters', 'cagr',           'APAC',  2025, 2030, 7.4,  'PCT',   'Forecast period 2025-2030', 6),
('R-104', 'Smart electricity meters', 'regional_share', 'China', 2024, 2024, 52.0, 'PCT',   'China share of the Asia-Pacific market', 7),
('R-105', 'EV charging infrastructure', 'market_size',    'Global', 2024, 2024, 32.5, 'USD_B', 'Hardware, software and installation services', 4),
('R-105', 'EV charging infrastructure', 'cagr',           'Global', 2025, 2030, 19.6, 'PCT',   'Forecast period 2025-2030', 5),
('R-105', 'EV charging infrastructure', 'regional_share', 'APAC',   2024, 2024, 54.0, 'PCT',   'Share of global market size', 6),
('R-106', 'Smart home appliances', 'market_size',    'Global', 2024, 2024, 46.8, 'USD_B', 'Connected major and small appliances', 3),
('R-106', 'Smart home appliances', 'cagr',           'Global', 2025, 2030, 12.1, 'PCT',   'Forecast period 2025-2030', 4),
('R-106', 'Smart home appliances', 'regional_share', 'APAC',   2024, 2024, 35.0, 'PCT',   'Share of global market size', 5);

INSERT INTO clients (id, company, contact_email) VALUES
('C-01', 'Northwind Utilities', 'ops@example.com'),
('C-02', 'Blue Delta Infra', 'procurement@example.com'),
('C-03', 'Harbor Grid Energy', 'grid@example.com');

INSERT INTO client_purchases (client_id, report_id, purchased_at) VALUES
('C-01', 'R-101', '2025-03-15'),
('C-01', 'R-103', '2025-02-01'),
('C-02', 'R-103', '2025-02-20'),
('C-03', 'R-104', '2025-03-01'),
('C-03', 'R-105', '2025-04-10');
