from http.client import CREATED, OK, BAD_REQUEST
from unittest import skip
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db.backends.dummy.base import ignore
from django.forms.formsets import formset_factory
from django.test.client import Client
from django.test import TestCase
from django_nose.tools import assert_ok, assert_code
from django_webtest import WebTest
from nose.tools import raises
from webtest import AppError
from orders.forms import OrderItemForm

from orders.models import Grain, Supplier, Hop

ORDER_GRAINS_URL = reverse('order_grain')
ORDER_HOPS_URL = reverse('order_hops')


class _CommonMixin(object):
    def setUp(self):
        self.user = User.objects.create_user('temporary', 'temporary@gmail.com', 'temporary')
        self.gladfields = Supplier.objects.create(name="Gladfields")
        self.nzhops = Supplier.objects.create(name="NZ Hops")
        self.munich = Grain.objects.create(
            name="Munich",
            unit_cost=12.5,
            unit_size=Grain.UNIT_SIZE_SACK,
            supplier=self.gladfields)
        self.sauvin = Hop.objects.create(
            name="Nelson Sauvin",
            unit_cost=4,
            unit_size=Hop.UNIT_SIZE_100G,
            supplier=self.nzhops)


class _IngredientGetBase(TestCase, _CommonMixin):
    url = None

    def setUp(self):
        _CommonMixin.setUp(self)
        self.client = Client()

    def tearDown(self):
        self.client.logout()

    def test_not_logged_in_redirected_to_login_page(self):
        expected_url = "%s?next=%s" % (reverse('login'), self.url)
        print(expected_url)
        response = self.client.get(self.url)
        self.assertRedirects(response, expected_url)
        response = self.client.post(self.url, data={})
        self.assertRedirects(response, expected_url)


class _IngredientPostBase(WebTest, _CommonMixin):
    def setUp(self):
        _CommonMixin.setUp(self)

    def _login(self):
        form = self.app.get(reverse('login')).form
        form['username'] = 'temporary'
        form['password'] = 'temporary'
        response = form.submit().follow()
        assert_code(response, OK)


class TestGrainsGet(_IngredientGetBase):
    url = ORDER_GRAINS_URL

    def test_get_happy_path(self):
        self.client.login(username='temporary', password='temporary')
        response = self.client.get(self.url)
        assert_ok(response)
        formset_ = response.context['formset']
        ingredients = [f.ingredient for f in formset_]
        self.assertIn(self.munich, ingredients)


class TestGrainsPost(_IngredientPostBase):
    def test_post_happy_path(self):
        self._login()
        response = self.app.get(ORDER_GRAINS_URL)
        add_grain_to_order_form = response.forms.get(0)
        add_grain_to_order_form['form-0-quantity'] = 5
        response = add_grain_to_order_form.submit()
        assert_code(response, CREATED)

        cart_form = response.forms.get(1)
        self.assertEqual("Munich", cart_form.get('ingredient_name').value)
        self.assertEqual('5', cart_form.get('quantity').value)

    @raises(AppError)
    def test_post_invalid_data_returns_400(self):
        self._login()
        response = self.app.get(ORDER_GRAINS_URL)
        add_grain_to_order_form = response.forms.get(0)
        add_grain_to_order_form['form-0-quantity'] = "bad_quantity"
        add_grain_to_order_form.submit()


class TestHopsGet(_IngredientGetBase):
    url = ORDER_HOPS_URL

    def test_get_happy_path(self):
        self.client.login(username='temporary', password='temporary')
        response = self.client.get(self.url)
        assert_ok(response)
        formset_ = response.context['formset']
        ingredients = [f.ingredient for f in formset_]
        self.assertIn(self.sauvin, ingredients)


class TestHopsPost(_IngredientPostBase):
    def test_post_happy_path(self):
        self._login()
        response = self.app.get(ORDER_HOPS_URL)
        add_grain_to_order_form = response.forms.get(0)
        add_grain_to_order_form['form-0-quantity'] = 5
        response = add_grain_to_order_form.submit()
        assert_code(response, CREATED)

        cart_form = response.forms.get(1)
        self.assertEqual("Nelson Sauvin", cart_form.get('ingredient_name').value)
        self.assertEqual('5', cart_form.get('quantity').value)

    @raises(AppError)
    def test_post_invalid_data_returns_400(self):
        self._login()
        response = self.app.get(ORDER_HOPS_URL)
        add_grain_to_order_form = response.forms.get(0)
        add_grain_to_order_form['form-0-quantity'] = "bad_quantity"
        add_grain_to_order_form.submit()