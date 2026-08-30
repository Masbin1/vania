# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class IncentiveRule(models.Model):
    """Versioned rule header: base rate, bonus rate, discount gate, tier table."""
    _name = 'incentive.rule'
    _description = 'Incentive Rule Version'
    _order = 'date_from desc'

    name = fields.Char(required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    base_rate = fields.Float(
        string='Base Rate', digits=(16, 6), default=0.0075,
        help="0.0075 = 0.75%. Multiplied by the tier allocation to obtain the "
             "effective payout rate.")
    bonus_rate = fields.Float(
        string='Bonus Rate', digits=(16, 6), default=0.01,
        help="Flat rate applied to the bonus-based bucket. No tiering.")
    max_discount = fields.Float(
        string='Max Eligible Discount (%)', default=35.0,
        help="S07: invoice LINES with a discount above this value are excluded "
             "from the eligible base. The rest of the invoice stays eligible.")
    cap_tier_in_mixed = fields.Boolean(
        string='Cap Tier 5 in Mixed Scenario', default=True,
        help="S18: when a salesperson has a bonus-based target, the incentive "
             "portion may not use the 105% allocation of tier 5.")
    mixed_cap_tier_level = fields.Integer(
        string='Mixed Scenario Cap Level', default=4,
        help="Highest tier level allowed on the incentive bucket when the "
             "mixed scenario is active.")

    tier_ids = fields.One2many(
        'incentive.rule.tier',
        'rule_id',
        string='Tiers',
        copy=True,
    )
    @api.constrains('tier_ids')
    def _check_tiers(self):
        for rule in self:
            if not rule.tier_ids:
                continue
            tiers = rule.tier_ids.sorted('achievement_min')
            for prev, curr in zip(tiers, tiers[1:]):
                if prev.achievement_max > curr.achievement_min:
                    raise ValidationError(_(
                        'Tier ranges overlap: %s ends at %s but %s starts at %s.'
                    ) % (prev.name, prev.achievement_max, curr.name, curr.achievement_min))

    def _get_tier(self, achievement_pct, is_mixed=False):
        """Return the tier record matching ``achievement_pct`` (a fraction: 0.86 = 86%).

        Boundary convention -- IMPORTANT, see the open questions in the FSD:
        a tier matches when  min <= achievement < max, EXCEPT the top tier
        which is open-ended. This makes exactly 75.0% fall into Tier 1, which
        is what the client's own new-hire use case (30M/40M -> Tier 1) expects.
        """
        self.ensure_one()
        tiers = self.tier_ids.sorted('achievement_min')
        matched = self.env['incentive.rule.tier']
        for tier in tiers:
            if achievement_pct >= tier.achievement_min and (
                    tier.is_top_tier or achievement_pct < tier.achievement_max):
                matched = tier
        if not matched and tiers:
            matched = tiers[0]
        if matched and is_mixed and self.cap_tier_in_mixed:
            if matched.level > self.mixed_cap_tier_level:
                capped = tiers.filtered(lambda t: t.level == self.mixed_cap_tier_level)
                if capped:
                    matched = capped[0]
        return matched


class IncentiveRuleTier(models.Model):
    _name = 'incentive.rule.tier'
    _description = 'Incentive Tier'
    _order = 'level'

    rule_id = fields.Many2one('incentive.rule', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    level = fields.Integer(required=True)

    achievement_min = fields.Float(
        string='Achievement From', digits=(16, 2),
        help="Stored as a fraction: 0.75 = 75%.")
    achievement_max = fields.Float(
        string='Achievement To', digits=(16, 2),
        help="Exclusive upper bound. Ignored on the top tier.")
    is_top_tier = fields.Boolean(
        string='Open-ended',
        help="Tick on the highest tier so that it has no upper bound.")

    allocation = fields.Float(
        string='Allocation', digits=(16, 2), default=0.0,
        help="0.4 = 40% of the base rate is paid out.")
    base_rate = fields.Float(related='rule_id.base_rate', readonly=True)
    payout_rate = fields.Float(
        string='Payout Rate', compute='_compute_payout_rate',
        store=True, digits=(16, 4))
    note = fields.Char()

    @api.depends('allocation', 'rule_id.base_rate')
    def _compute_payout_rate(self):
        for tier in self:
            tier.payout_rate = tier.allocation * tier.rule_id.base_rate
